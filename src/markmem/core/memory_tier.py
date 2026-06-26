#!/usr/bin/env python3
"""
memory_tier.py — Hot→Warm-Tiering für MEMORY.md (Gedächtnis-v3, Phase 4).

Problem: MEMORY.md (immer beim SessionStart geladen) ist über das Ladelimit
(~24KB) gewachsen → Inhalt dahinter (u.a. die ⛔ HARD-GATES) wird abgeschnitten.

Lösung (deterministisch, NICHT LLM): die historischen `## 🔥 CURRENT STATE`-
Sektionen ins Warm-Tier (MEMORY_DEEP.md) verschieben. Die neuesten K bleiben Hot.
Alles andere (Regeln, HARD-GATES, Anti-Patterns, Whitelist…) bleibt unangetastet.

SICHERHEIT (fehlerfrei-by-design):
  - Inhalts-Erhalt-Invariante: jeder [link](x.md) und jeder [[slug]] aus der alten
    MEMORY.md MUSS nachher in (MEMORY.md ∪ MEMORY_DEEP.md) vorkommen. Sonst Abbruch.
  - Jede verschobene Sektion MUSS wortgleich in MEMORY_DEEP.md landen. Sonst Abbruch.
  - Backup von MEMORY.md + MEMORY_DEEP.md vor jedem Schreibvorgang.
  - Default = DRY-RUN (zeigt nur, was passieren würde). Schreibt erst mit --apply.

Aufruf:
  memory_tier.py                  # Dry-run: Plan + Größen + Invariante
  memory_tier.py --keep 2         # die neuesten 2 CURRENT-STATE bleiben Hot (Default 2)
  memory_tier.py --apply          # tatsächlich verschieben (mit Backup)
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime

from markmem import paths

HOT = paths.INDEX_FILE
WARM = paths.DEEP_FILE

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+\.md)\)")
WIKI_RE = re.compile(r"\[\[([a-zA-Z0-9_\-]+)\]\]")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
CURRENT_STATE_RE = re.compile(r"CURRENT STATE", re.IGNORECASE)


def split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """→ (preamble, [(header_line, full_section_text)]). Sektion = ab '## ' bis vor
    nächstem '## '. Preamble = alles vor dem ersten '## '."""
    lines = text.splitlines(keepends=True)
    hdr_idx = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if not hdr_idx:
        return text, []
    preamble = "".join(lines[: hdr_idx[0]])
    sections = []
    for k, i in enumerate(hdr_idx):
        end = hdr_idx[k + 1] if k + 1 < len(hdr_idx) else len(lines)
        sections.append((lines[i].rstrip("\n"), "".join(lines[i:end])))
    return preamble, sections


def links_in(text: str) -> set[str]:
    return set(LINK_RE.findall(text)) | {f"[[{w}]]" for w in WIKI_RE.findall(text)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", type=int, default=2, help="neueste N CURRENT-STATE-Sektionen Hot behalten")
    ap.add_argument("--apply", action="store_true", help="tatsächlich schreiben (sonst Dry-Run)")
    args = ap.parse_args()

    old = HOT.read_text(encoding="utf-8")
    preamble, sections = split_sections(old)

    # CURRENT-STATE-Sektionen identifizieren + nach Datum sortieren (neueste zuerst)
    cs = [(h, b) for (h, b) in sections if CURRENT_STATE_RE.search(h)]

    def sort_key(hb):
        m = DATE_RE.search(hb[0])
        # (PM)/(Nacht) als Tie-Breaker grob nach unten/oben
        d = m.group(1) if m else "0000-00-00"
        pm = 1 if "(PM)" in hb[0] or "(Nacht)" in hb[0] else 0
        return (d, pm)

    cs_sorted = sorted(cs, key=sort_key, reverse=True)
    keep = set(id(b) for _, b in cs_sorted[: args.keep])
    demote = [(h, b) for (h, b) in cs if id(b) not in keep]

    if not demote:
        print("[ok] Nichts zu verschieben — MEMORY.md bereits schlank.")
        return 0

    # Neue Hot-Datei: alle Sektionen außer den demoteten; an Stelle des ersten
    # demoteten CURRENT-STATE einen Pointer einsetzen.
    pointer = ("## 🗄 Ältere CURRENT-STATE-Historie → [MEMORY_DEEP.md](MEMORY_DEEP.md)\n\n"
               "> Auto-getiert. Ältere Lage-Stände liegen im Warm-Tier (semantisch via "
               "`memory_retrieve.py`/`vector_store.py` abrufbar).\n\n")
    demote_ids = {id(b) for _, b in demote}
    # HARD-GATES-Sektion identifizieren (muss laut Präambel ganz oben/immer geladen sein)
    hardgates = next((b for h, b in sections if "HARD-GATES" in h), None)

    new_parts = [preamble]
    if hardgates is not None:  # Pflichtlektüre direkt nach der Präambel = immer im Ladefenster
        new_parts.append(hardgates if hardgates.endswith("\n") else hardgates + "\n")
    pointer_done = False
    for h, b in sections:
        if id(b) in demote_ids:
            if not pointer_done:
                new_parts.append(pointer)
                pointer_done = True
            continue
        if b is hardgates:
            continue  # schon oben eingefügt
        new_parts.append(b)
    new_hot = "".join(new_parts)

    # Warm-Tier: bestehenden Inhalt + verschobene Sektionen anhängen
    old_warm = WARM.read_text(encoding="utf-8") if WARM.exists() else "# MEMORY_DEEP — Warm-Tier (on-demand)\n"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    moved_block = f"\n\n---\n\n# 🗄 Auto-getierte CURRENT-STATE-Historie ({stamp})\n\n" + "\n".join(b.rstrip() for _, b in demote) + "\n"
    new_warm = old_warm.rstrip() + "\n" + moved_block

    # ---- Inhalts-Erhalt-Invariante (HARTES GATE) -------------------------------
    old_links = links_in(old)
    new_links = links_in(new_hot) | links_in(new_warm)
    lost_links = old_links - new_links
    bodies_ok = all(b.strip() in new_warm for _, b in demote)

    print("════ MEMORY.md Tiering — Plan ════")
    print(f"  Hot  jetzt:  {len(old.encode())//1024} KB / {old.count(chr(10))+1} Z")
    print(f"  Hot  nachher:{len(new_hot.encode())//1024} KB / {new_hot.count(chr(10))+1} Z")
    print(f"  CURRENT-STATE: {len(cs)} total → {args.keep} bleiben Hot, {len(demote)} → Warm")
    print(f"  Verschoben ({len(demote)}):")
    for h, _ in demote:
        print(f"    - {h[:78]}")
    print(f"  Behalten Hot ({len(cs)-len(demote)}):")
    for h, b in cs_sorted[: args.keep]:
        print(f"    + {h[:78]}")
    # HARD-GATES-Sichtbarkeit: Position der echten SEKTION (## …HARD-GATES…), nicht der Präambel-Erwähnung
    m_hg = re.search(r"^##\s+.*HARD-GATES", new_hot, re.MULTILINE)
    hg_pos = m_hg.start() if m_hg else -1
    hg_kb = len(new_hot[:hg_pos].encode()) / 1024 if hg_pos >= 0 else -1
    print(f"  ⛔ HARD-GATES landet bei: {hg_kb:.1f} KB (Ladelimit ~24KB → {'SICHTBAR ✅' if 0<=hg_kb<24 else 'NOCH ZU TIEF ⚠️'})")
    print("════ Inhalts-Erhalt-Invariante ════")
    print(f"  Links alt: {len(old_links)}  → erhalten: {'JA ✅' if not lost_links else 'NEIN ❌ '+str(lost_links)}")
    print(f"  Verschobene Sektionen wortgleich in Warm: {'JA ✅' if bodies_ok else 'NEIN ❌'}")

    if lost_links or not bodies_ok:
        print("\n[ABBRUCH] Invariante verletzt — es wird NICHTS geschrieben.", file=sys.stderr)
        return 1

    if not args.apply:
        print("\n[dry-run] Alles ok. Mit --apply tatsächlich anwenden (Backup wird erstellt).")
        return 0

    # ---- Schreiben (mit Backup) ------------------------------------------------
    bts = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(HOT, HOT.with_suffix(f".md.bak.{bts}"))
    if WARM.exists():
        shutil.copy2(WARM, WARM.with_suffix(f".md.bak.{bts}"))
    HOT.write_text(new_hot, encoding="utf-8")
    WARM.write_text(new_warm, encoding="utf-8")
    print(f"\n[apply] Geschrieben. Backups: MEMORY.md.bak.{bts} / MEMORY_DEEP.md.bak.{bts}")
    print(f"  MEMORY.md jetzt {len(new_hot.encode())//1024} KB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
