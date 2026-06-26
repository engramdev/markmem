#!/usr/bin/env python3
"""
dashboard.py — memDash · Gedächtnis-v3 Live-Dashboard (responsiv, konsistent).

Passt Rahmen + Layout dynamisch an die Terminal-Größe an (Mac-Querformat vs.
iPhone-Hochformat über SSH), rechnet Textbreiten Unicode-korrekt und degradiert
Farben Truecolor → 256 → 16 → aus. Konsistentes Spalten-Raster, keine Emojis,
Start-Animation.

Aufruf:  ~/memdash            (Snapshot)
         ~/memdash --watch    (Live, refresht alle 5s, sofort bei Resize)

Override / Test:
  COLUMNS=40 MEMDASH_MODUS=schmal MEMDASH_FARBEN=aus MEMDASH_INTRO=aus ~/memdash

Pure stdlib + bereits installiertes wcwidth. Fail-open, kein Daemon.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

try:
    from wcwidth import wcswidth as _wcswidth   # bereits installiert (0.2.x)
except Exception:
    _wcswidth = None

from markmem.config import MEMORY_DIR, GRAPH
from markmem import paths

MEM = MEMORY_DIR
SKIP = paths.SKIP_FILES

# ─────────────────────── Breakpoints (wie CSS-Media-Queries) ───────────────────────
SCHMAL_MAX = 55          # Spalten < 56  → "schmal" (iPhone-Hochformat)
MITTEL_MAX = 99          # 56–99         → "mittel"
#                          >= 100        → "breit"
REFRESH_SEK = 5
HOCHFORMAT_VERH = 0.42   # Zeilen/Spalten >= Wert ⇒ eher Hochformat

# Konsistentes Raster: Label-/Wertspalten pro Modus (Balken füllt den Rest)
LABEL_JE_MODUS = {"breit": 15, "mittel": 13, "schmal": 9}
WERT_JE_MODUS = {"breit": 17, "mittel": 15, "schmal": 11}

# ─────────────────────── Farbpalette (eine Quelle für alles) ───────────────────────
PALETTE = {
    "AKZENT":    {"tc": (90, 200, 245),  "c256": 39,  "c16": 96},
    "ERFOLG":    {"tc": (95, 215, 135),  "c256": 78,  "c16": 92},
    "WARNUNG":   {"tc": (240, 195, 90),  "c256": 221, "c16": 93},
    "GEFAHR":    {"tc": (240, 100, 100), "c256": 203, "c16": 91},
    "INFO":      {"tc": (125, 170, 245), "c256": 75,  "c16": 94},
    "LILA":      {"tc": (185, 150, 245), "c256": 141, "c16": 95},
    "GEDAEMPFT": {"tc": (135, 145, 160), "c256": 245, "c16": 90},
    "TEXT":      {"tc": (230, 236, 246), "c256": 254, "c16": 97},
    "RAHMEN":    {"tc": (70, 120, 145),  "c256": 66,  "c16": 36},
    "_DUNKEL":   {"tc": (18, 22, 28),    "c256": 235, "c16": 30},
}

# Laufzeit-Zustand (pro Render gesetzt)
BREITE, HOEHE = 80, 24
MODUS = "mittel"
FARBSTUFE = "truecolor"
INHALT, BARW, LABELB, WERTB = 76, 24, 13, 15
RST, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
ANSI_RE = re.compile(r"\033\[[0-9;]*m")


# ═══════════════════════════ Terminal & Fähigkeiten ═══════════════════════════
def terminalgroesse() -> tuple[int, int]:
    spalten = os.environ.get("COLUMNS")
    if spalten and spalten.isdigit():
        try:
            zeilen = int(os.environ.get("LINES", "24"))
        except ValueError:
            zeilen = 24
        return max(20, int(spalten)), zeilen
    try:
        g = shutil.get_terminal_size(fallback=(80, 24))
        return max(20, g.columns), g.lines
    except Exception:
        return 80, 24


def farbstufe_ermitteln() -> str:
    wahl = os.environ.get("MEMDASH_FARBEN", "").lower()
    if wahl in ("aus", "off", "0", "none", "nein"):
        return "aus"
    if wahl in ("truecolor", "256", "16"):
        return wahl
    colorterm = os.environ.get("COLORTERM", "").lower()
    term = os.environ.get("TERM", "")
    if "truecolor" in colorterm or "24bit" in colorterm:
        return "truecolor"
    if "256" in term:
        return "256"
    if term in ("", "dumb"):
        return "256"
    return "truecolor"


def modus_ermitteln(spalten: int, zeilen: int) -> str:
    wahl = os.environ.get("MEMDASH_MODUS", "").lower()
    if wahl in ("schmal", "mittel", "breit"):
        return wahl
    eff = spalten
    if spalten and zeilen / spalten >= HOCHFORMAT_VERH and spalten < 120:
        eff = int(spalten * 0.9)
    if eff <= SCHMAL_MAX:
        return "schmal"
    if eff <= MITTEL_MAX:
        return "mittel"
    return "breit"


# ═══════════════════════════ Unicode-Breite & Kürzen ═══════════════════════════
def ohne_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def zellbreite(text: str) -> int:
    s = ohne_ansi(text)
    if _wcswidth is not None:
        w = _wcswidth(s)
        if w is not None and w >= 0:
            return w
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def beschneiden(text: str, maxbreite: int) -> str:
    if zellbreite(text) <= maxbreite:
        return text
    out, sicht, i = [], 0, 0
    while i < len(text):
        m = ANSI_RE.match(text, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        ch = text[i]
        w = zellbreite(ch)
        if sicht + w > maxbreite - 1:
            break
        out.append(ch)
        sicht += w
        i += 1
    out.append(f"{DIM}…{RST}")
    return "".join(out)


def text_kuerzen(s: str, maxbreite: int) -> str:
    if zellbreite(s) <= maxbreite:
        return s
    out, w = "", 0
    for ch in s:
        cw = zellbreite(ch)
        if w + cw > maxbreite - 1:
            break
        out += ch
        w += cw
    return out + "…"


def name_kuerzen(name: str, maxbreite: int) -> str:
    """Lange Dateinamen kürzen — Anfang + ".md"-Endung sichtbar."""
    if zellbreite(name) <= maxbreite:
        return name
    suffix = ".md" if name.endswith(".md") else ""
    stamm = name[: -len(suffix)] if suffix else name
    frei = maxbreite - 1 - zellbreite(suffix)
    if frei < 4:
        return name[: max(1, maxbreite)]
    kopf = stamm
    while zellbreite(kopf) > frei and kopf:
        kopf = kopf[:-1]
    return f"{kopf}…{suffix}"


# ═══════════════════════════ Farbe / Chips / Badges / Balken ═══════════════════════════
def fc(name: str, bg: bool = False) -> str:
    if FARBSTUFE == "aus":
        return ""
    col = PALETTE.get(name, PALETTE["TEXT"])
    if FARBSTUFE == "truecolor":
        r, g, b = col["tc"]
        return f"\033[{48 if bg else 38};2;{r};{g};{b}m"
    if FARBSTUFE == "256":
        return f"\033[{48 if bg else 38};5;{col['c256']}m"
    code = col["c16"]
    return f"\033[{code + 10 if bg else code}m"


def c(text, name=None, bold=False) -> str:
    if FARBSTUFE == "aus":
        return text
    pre = (fc(name) if name else "") + (BOLD if bold else "")
    return f"{pre}{text}{RST}" if pre else text


def chip(label: str, name: str) -> str:
    if FARBSTUFE == "aus":
        return f"[{label}]"
    fg = "_DUNKEL" if name in ("ERFOLG", "WARNUNG") else "TEXT"
    return f"{fc(name, bg=True)}{fc(fg)}{BOLD} {label} {RST}"


def badge(text: str, name: str = "GEDAEMPFT") -> str:
    if FARBSTUFE == "aus":
        return f"({text})"
    fg = "_DUNKEL" if name in ("ERFOLG", "WARNUNG") else "TEXT"
    return f"{fc(name, bg=True)}{fc(fg)}{BOLD} {text} {RST}"


def grad_name(frac: float) -> str:
    if frac >= 0.7:
        return "ERFOLG"
    if frac >= 0.45:
        return "WARNUNG"
    return "GEFAHR"


def balken(frac: float, breite: int, name: str = None) -> str:
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * breite))
    name = name or grad_name(frac)
    if FARBSTUFE == "aus":
        return "#" * n + "-" * (breite - n)
    return f"{fc(name)}{'█' * n}{fc('GEDAEMPFT')}{'░' * (breite - n)}{RST}"


SPARK = "▁▂▃▄▅▆▇█"


def sparkbalken(werte: list[int], name: str = "INFO") -> str:
    if not werte:
        return ""
    mx = max(werte) or 1
    z = "".join(SPARK[min(7, int(v / mx * 7))] for v in werte)
    return z if FARBSTUFE == "aus" else fc(name) + z + RST


def rechts_buendig(wert: str, breite: int) -> str:
    """Wert rechtsbündig in fester Spaltenbreite (für saubere Zahlen-Kolonne)."""
    pad = max(0, breite - zellbreite(wert))
    return " " * pad + wert


# ═══════════════════════════ Zeilen-Bausteine (einheitliches Raster) ═══════════════════════════
def metrik(label: str, frac: float, wert: str, name: str = None) -> str:
    """label (LABELB) · Balken (BARW, füllt) · Wert (WERTB, rechtsbündig). Überall gleich."""
    name = name or grad_name(frac)
    lab = text_kuerzen(label, LABELB)
    lpad = max(0, LABELB - zellbreite(lab))
    wpad = max(0, WERTB - zellbreite(wert))
    return f"{c(lab, 'GEDAEMPFT')}{' ' * lpad} {balken(frac, BARW, name)} {' ' * wpad}{c(wert, name, bold=True)}"


def vergleich(label: str, was, jetzt, einheit="", besser="hoch") -> str:
    """Vorher→Nachher (Vergleich, kein Level): label (LABELB) · was ▸ jetzt. Pfeil grün/rot."""
    verbessert = (jetzt > was) if besser == "hoch" else (jetzt < was)
    pfeil = c("▲" if besser == "hoch" else "▼", "ERFOLG" if verbessert else "GEFAHR", bold=True)
    lab = text_kuerzen(label, LABELB)
    lpad = max(0, LABELB - zellbreite(lab))
    wert = (c(rechts_buendig(f"{was:g}{einheit}", 7), "GEDAEMPFT")
            + f"  {pfeil}  " + c(f"{jetzt:g}{einheit}", "ERFOLG", bold=True))
    return f"{c(lab, 'GEDAEMPFT')}{' ' * lpad} {wert}"


# ═══════════════════════════ Panel-Renderer (responsiv) ═══════════════════════════
def abschnitt(titel: str, zeilen: list[str], hint: str = ""):
    """breit/mittel = volle Box (dynamischer Rahmen); schmal = Titel-Trennlinie + linksbündig."""
    boxed = MODUS in ("breit", "mittel")
    kopf = titel if not hint else f"{titel}  {c(hint, 'GEDAEMPFT')}"
    kopf_breit = zellbreite(ohne_ansi(kopf))
    if boxed:
        innen = BREITE - 4
        if kopf_breit > BREITE - 5:
            kopf = text_kuerzen(titel, BREITE - 5)
            kopf_breit = zellbreite(kopf)
        fuell = max(0, BREITE - 5 - kopf_breit)
        ktxt = f"{fc('AKZENT')}{BOLD}{titel}{RST}" + (f"  {c(hint, 'GEDAEMPFT')}" if hint and kopf_breit <= BREITE - 5 else "")
        print(f"{fc('RAHMEN')}╭─ {ktxt} {fc('RAHMEN')}{'─' * fuell}╮{RST}")
        for z in zeilen:
            z = beschneiden(z, innen)
            pad = max(0, innen - zellbreite(z))
            print(f"{fc('RAHMEN')}│{RST} {z}{' ' * pad} {fc('RAHMEN')}│{RST}")
        print(f"{fc('RAHMEN')}╰{'─' * (BREITE - 2)}╯{RST}")
    else:
        k = text_kuerzen(titel, BREITE - 4)
        fuell = max(0, BREITE - 4 - zellbreite(k))
        print(f"{fc('AKZENT')}{BOLD}━━ {k} {RST}{fc('RAHMEN')}{'━' * fuell}{RST}")
        for z in zeilen:
            print(beschneiden(z, BREITE))
    print()


# ═══════════════════════════ Daten laden (fail-safe) ═══════════════════════════
def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def lade_karten():
    by_type, alle = {}, []
    type_re = re.compile(r"^\s*type:\s*(\w+)", re.MULTILINE)
    conf_re = re.compile(r"^\s*confidence:\s*([\d.]+)", re.MULTILINE)
    for p in sorted(MEM.glob("*.md")):
        if p.name in SKIP:
            continue
        txt = safe(lambda p=p: p.read_text(encoding="utf-8"), "")
        kopf = txt[:600]
        t = (type_re.search(kopf).group(1) if type_re.search(kopf) else "?")
        cf = safe(lambda: float(conf_re.search(kopf).group(1)), None)
        by_type.setdefault(t, []).append((p.name, cf, len(txt.encode()), txt.count("\n") + 1))
        alle.append((p.name, cf, len(txt.encode()), txt.count("\n") + 1))
    return by_type, alle


def lade_vindex():
    db = paths.VECTOR_INDEX
    if not db.exists():
        return None
    con = sqlite3.connect(str(db))
    try:
        ch = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        fi = con.execute("SELECT COUNT(DISTINCT file) FROM chunks").fetchone()[0]
        meta = dict(con.execute("SELECT key,value FROM meta").fetchall())
        return {"chunks": ch, "files": fi, "model": meta.get("model", "?"), "dim": meta.get("dim", "?")}
    finally:
        con.close()


def lade_graph():
    if not GRAPH.exists():
        return 0, 0
    e = r = 0
    for line in GRAPH.read_text(encoding="utf-8").splitlines():
        if '"type": "entity"' in line or '"type":"entity"' in line:
            e += 1
        elif '"type": "relation"' in line or '"type":"relation"' in line:
            r += 1
    return e, r


def jlade(p, default=None):
    return safe(lambda: json.loads(Path(p).read_text(encoding="utf-8")), default)


def inbox_zaehlen(name, muster="^## "):
    p = paths.INBOX / name
    return 0 if not p.exists() else len(re.findall(muster, p.read_text(encoding="utf-8"), re.MULTILINE))


# ═══════════════════════════ Start-Animation ═══════════════════════════
def intro():
    """Kurze, ruhige Start-Animation mit 'memDash' (Highlight-Sweep + Füllbalken)."""
    if not sys.stdout.isatty():
        return
    if os.environ.get("MEMDASH_INTRO", "").lower() in ("aus", "0", "off", "nein"):
        return
    global BREITE, FARBSTUFE
    BREITE, _ = terminalgroesse()
    FARBSTUFE = farbstufe_ermitteln()
    gross = " ".join("memDash")              # m e m D a s h
    sub = "Gedächtnis-v3 · Live-Dashboard"
    barw = min(34, max(14, BREITE - 6))

    def mitte(s):
        return " " * max(0, (BREITE - zellbreite(ohne_ansi(s))) // 2) + s

    frames = 22
    for fr in range(frames + 1):
        frac = fr / frames
        hl = frac * len(gross)
        teile = []
        for i, ch in enumerate(gross):
            if ch == " ":
                teile.append(" ")
            elif abs(i - hl) < 1.6:
                teile.append(c(ch, "ERFOLG", bold=True))
            elif i < hl:
                teile.append(c(ch, "AKZENT", bold=True))
            else:
                teile.append(c(ch, "GEDAEMPFT"))
        n = int(frac * barw)
        leiste = c("█" * n, "AKZENT") + c("░" * (barw - n), "GEDAEMPFT")
        print("\033[2J\033[H", end="")
        print("\n\n\n")
        print(mitte("".join(teile)))
        print()
        print(mitte(c(sub, "GEDAEMPFT")))
        print()
        print(mitte(f"{c('[', 'RAHMEN')}{leiste}{c(']', 'RAHMEN')}"))
        sys.stdout.flush()
        time.sleep(0.04)
    time.sleep(0.18)
    print("\033[2J\033[H", end="")


# ═══════════════════════════ Render ═══════════════════════════
def render():
    global BREITE, HOEHE, MODUS, FARBSTUFE, INHALT, BARW, LABELB, WERTB
    BREITE, HOEHE = terminalgroesse()
    FARBSTUFE = farbstufe_ermitteln()
    MODUS = modus_ermitteln(BREITE, HOEHE)
    INHALT = BREITE if MODUS == "schmal" else BREITE - 4
    LABELB = LABEL_JE_MODUS[MODUS]
    WERTB = WERT_JE_MODUS[MODUS]
    BARW = max(6, INHALT - LABELB - WERTB - 2)

    by_type, alle = lade_karten()
    vi = lade_vindex()
    ents, rels = lade_graph()
    cfg = jlade(paths.RETRIEVAL_CONFIG, {}) or {}
    ev = jlade(paths.EVAL_JSON, {}) or {}
    kal = jlade(paths.KALIB_FILE, {"miscalibrated": []}) or {"miscalibrated": []}

    # ── Kopf + Legende (was sehe ich) ──
    branch = safe(lambda: subprocess.run(["git", "-C", str(MEM), "rev-parse", "--abbrev-ref", "HEAD"],
                                         capture_output=True, text=True).stdout.strip(), "?")
    print(beschneiden(c("memDash", "AKZENT", bold=True) + c("  —  Live-Zustand des KI-Gedächtnisses", "GEDAEMPFT"), BREITE))
    print(beschneiden(c(f"branch {branch} · {MODUS} · {BREITE}×{HOEHE} · {FARBSTUFE} · {datetime.now():%H:%M}", "GEDAEMPFT"), BREITE))
    legende = (c("Balken", "TEXT") + c(" = Anteil/Level   ", "GEDAEMPFT")
               + c("grün", "ERFOLG") + c(" gut · ", "GEDAEMPFT")
               + c("gelb", "WARNUNG") + c(" mittel · ", "GEDAEMPFT")
               + c("rot", "GEFAHR") + c(" niedrig", "GEDAEMPFT"))
    print(beschneiden(legende, BREITE))
    print()

    # ── Transformation ──
    mm = safe(lambda: paths.INDEX_FILE.stat().st_size / 1024, 0)
    tcfg = cfg.get("_tuned", {}) or {}
    abschnitt("TRANSFORMATION", [
        vergleich("MEMORY.md", 71, round(mm, 1), "KB", "runter"),
        vergleich("Recall@1", round(tcfg.get("baseline_recall@1", 0.80) * 100), round(tcfg.get("recall@1", 0.857) * 100), "%", "hoch"),
        vergleich("Graph", 14, ents, "", "hoch"),
        vergleich("Chunks", 0, (vi or {}).get("chunks", 0), "", "hoch"),
    ], hint="vorher → nachher")

    # ── Korpus ──
    total = len(alle) or 1
    typfarbe = {"feedback": "ERFOLG", "project": "INFO", "reference": "LILA", "user": "WARNUNG", "?": "GEDAEMPFT"}
    zeilen = []
    for t in sorted(by_type, key=lambda x: -len(by_type[x]))[:6]:
        n = len(by_type[t])
        zeilen.append(metrik(t, n / total, f"{n}  {n/total*100:>2.0f}%", typfarbe.get(t, "GEDAEMPFT")))
    kb = sum(x[2] for x in alle) / 1024
    zeilen.append(c(f"Summe {total} Karten · {kb:.0f} KB", "GEDAEMPFT"))
    abschnitt("KORPUS", zeilen, hint="Karten nach Typ")

    # ── Tiers ──
    LIMIT = 24.4
    zeilen = []
    for fn, lab in [("MEMORY.md", "Hot"), ("MEMORY_RULES.md", "Hook/Regeln"), ("MEMORY_DEEP.md", "Warm")]:
        sz = safe(lambda fn=fn: (MEM / fn).stat().st_size / 1024, 0)
        if fn == "MEMORY.md":
            ok = sz <= LIMIT
            zeilen.append(metrik(lab, sz / LIMIT, f"{sz:.0f}/{LIMIT:.0f}KB {'voll' if ok else 'ÜBER'}", "ERFOLG" if ok else "GEFAHR"))
        else:
            zeilen.append(metrik(lab, min(sz / 60, 1), f"{sz:.0f} KB", "INFO" if "RULES" in fn else "GEDAEMPFT"))
    abschnitt("TIERS", zeilen, hint="Lade-Ebenen · Limit 24 KB")

    # ── Qualität ──
    zeilen = []
    if ev:
        for key, lab, name in [("vector_off", "Baseline", "GEDAEMPFT"),
                               ("vector_on", "+ Vektor", "ERFOLG"),
                               ("vector_rerank", "+ Rerank", "LILA")]:
            d = ev.get(key) or {}
            r1 = d.get("recall@1")
            if r1 is not None:
                zeilen.append(metrik(lab, r1, f"{r1*100:>4.1f}%", name))
        zeilen.append(c(f"Gold-Set n={ev.get('n','?')} · Trefferquote Recall@1", "GEDAEMPFT"))
    else:
        zeilen.append(c("keine Eval-Daten", "GEDAEMPFT"))
    abschnitt("QUALITÄT", zeilen, hint="gemessene Trefferquote")

    # ── Engine ──
    wts = cfg.get("weights") or {"bm25": 1, "vector": 1, "entity": 1}
    mxw = max(wts.values()) or 1
    zeilen = []
    for sig, name in [("bm25", "WARNUNG"), ("vector", "ERFOLG"), ("entity", "INFO")]:
        v = wts.get(sig, 1.0)
        zeilen.append(metrik(sig, v / mxw, f"{v:.1f}x", name))
    if vi:
        zeilen.append(c(f"{vi['chunks']} Chunks · {vi['model']} {vi['dim']}d", "GEDAEMPFT"))
    abschnitt("ENGINE", zeilen, hint="Such-Gewichte · selbst-getunt")

    # ── Lernen ──
    sack = safe(lambda: len(re.findall(r"^## ", paths.DEADEND_REGISTRY.read_text(encoding="utf-8"), re.MULTILINE)), 0)
    miscal = len(kal.get("miscalibrated", []))
    confs = [x[1] for x in alle if x[1] is not None]
    avgc = sum(confs) / len(confs) if confs else 0
    buckets = [0, 0, 0, 0, 0]
    for cf2 in confs:
        buckets[min(4, int(cf2 * 5))] += 1
    abschnitt("LERNEN", [
        f"{badge(str(sack), 'GEFAHR')} {c('Sackgassen (aktiv-hemmend)', 'GEDAEMPFT')}",
        f"{badge(str(miscal), 'WARNUNG')} {c('miskalibriert (Confidence trog)', 'GEDAEMPFT')}",
        metrik("Conf", avgc, f"{avgc*100:.0f}%", grad_name(avgc)),
        f"{c('Verteilung', 'GEDAEMPFT')} {sparkbalken(buckets, 'INFO')} {c('0.0 → 1.0', 'GEDAEMPFT')}",
    ], hint="Lern-Signale")

    # ── Inbox ──
    surp = inbox_zaehlen("surprises.md")
    corr = inbox_zaehlen("corrections.md")
    contra = inbox_zaehlen("contradictions_semantic.md", r"^## ⚔")
    cptxt = safe(lambda: (paths.INBOX / "compaction_proposals.md").read_text(encoding="utf-8"), "")
    nd = len(re.findall(r"(?m)^##.*DROP", cptxt))
    nm = len(re.findall(r"(?m)^##.*MERGE", cptxt))
    na = len(re.findall(r"(?m)^##.*ADD", cptxt))
    abschnitt("INBOX", [
        f"{badge(str(surp), 'LILA')} {c('Surprises', 'GEDAEMPFT')}    {badge(str(corr), 'WARNUNG')} {c('Korrekturen', 'GEDAEMPFT')}",
        f"{c('Verdichtung', 'GEDAEMPFT')}  {chip(f'{nd} DROP', 'GEFAHR')} {chip(f'{nm} MERGE', 'WARNUNG')} {chip(f'{na} ADD', 'ERFOLG')}",
        f"{badge(str(contra), 'AKZENT')} {c('Widerspruchs-Kandidat(en)', 'GEDAEMPFT')}",
    ], hint="wartet auf Review · nie auto")

    # ── Top-Karten ──
    namebreite = INHALT - (9 if MODUS != "schmal" else 8)
    hi = sorted([x for x in alle if x[1] is not None], key=lambda x: -x[1])[:3]
    gross = sorted(alle, key=lambda x: -x[2])[:3]
    zeilen = [c("nach Confidence", "ERFOLG")]
    for f, cf2, b, l in hi:
        zeilen.append(f"  {c(f'{cf2*100:>3.0f}%', 'ERFOLG', bold=True)} {c(name_kuerzen(f, namebreite), 'TEXT')}")
    zeilen.append(c("nach Größe", "INFO"))
    for f, cf2, b, l in gross:
        zeilen.append(f"  {c(f'{b/1024:>4.1f}KB', 'INFO', bold=True)} {c(name_kuerzen(f, namebreite), 'TEXT')}")
    abschnitt("TOP-KARTEN", zeilen, hint="wichtigste Karten")

    print(beschneiden(c("Markdown+git · HybridRAG · Lern-Schleife · selbst-tunend · fail-open", "GEDAEMPFT"), BREITE))


# ═══════════════════════════ Live-Modus (SIGWINCH) ═══════════════════════════
_resize = False


def _on_winch(signum, frame):
    global _resize
    _resize = True


def watch():
    global _resize
    try:
        signal.signal(signal.SIGWINCH, _on_winch)
    except (ValueError, AttributeError, OSError):
        pass
    try:
        while True:
            print("\033[2J\033[H", end="")
            render()
            print(c(f"↻ Live · alle {REFRESH_SEK}s · sofort bei Resize · Strg-C beendet", "GEDAEMPFT"))
            _resize = False
            for _ in range(int(REFRESH_SEK / 0.4)):
                if _resize:
                    break
                time.sleep(0.4)
    except KeyboardInterrupt:
        print(f"\n{c('memDash beendet.', 'GEDAEMPFT')}")


def main():
    if "--watch" in sys.argv:
        intro()
        watch()
    else:
        intro()
        print()
        render()
        print()


if __name__ == "__main__":
    main()
