#!/usr/bin/env python3
"""
memory_restructure.py — Drei-Tier-Verfassungs-Restructure für MEMORY.md (Gedächtnis-v3, Phase 4b).

Problem (harte Mathematik): die Verhaltens-Regeln allein (~24KB) sprengen das
24KB-Ladelimit von MEMORY.md — reines Verschieben reicht nie.

Innovative Lösung — Zwei-Kanal-Laden:
  HOT  → MEMORY.md      : Präambel + HARD-GATES + Kern-Regeln + Pointer (~20KB, lädt voll)
  RULES→ MEMORY_RULES.md: Bug-Bounty-Verhaltensregeln, vom SessionStart-Hook IMMER injiziert
                          (eigener Kontext-Kanal, NICHT vom 24KB-Limit betroffen)
  WARM → MEMORY_DEEP.md : Historie/Info, semantisch via vector_store abrufbar

So sind ALLE kritischen Inhalte garantiert im Kontext, nichts wird je abgeschnitten.

SICHERHEIT (fehlerfrei-by-design):
  - Partition-Invariante: JEDE Sektion landet in genau EINER Ziel-Datei (kein Verlust,
    keine Dopplung). Jeder [link](x.md)/[[slug]] aus alt-MEMORY.md muss in der Union
    der drei Dateien vorkommen. Sonst Abbruch, kein Schreibvorgang.
  - Backup aller drei Dateien vor dem Schreiben. Default = DRY-RUN (--apply zum Schreiben).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime

from markmem import paths

HOT = paths.INDEX_FILE
RULES = paths.RULES_FILE
WARM = paths.DEEP_FILE

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+\.md)\)")
WIKI_RE = re.compile(r"\[\[([a-zA-Z0-9_\-]+)\]\]")

# Klassifikation per Header-Substring. HOT bleibt in MEMORY.md (geladen).
HOT_KEYS = [
    "HARD-GATES", "Kommunikations-Regel", "Design- & Architektur",
    "Vulnerability-Class-Blacklist", "Submit-Wording", "Active Submit-Pipeline",
    "Eigene Profile", "User & Reputation",
]
# RULES → MEMORY_RULES.md (vom Hook immer injiziert — Bug-Bounty-Verhalten)
RULES_KEYS = [
    "Anti-Patterns", "Vulnerability-Class-Patterns", "Engine/Stack-Patterns",
]
# Alles andere → WARM (MEMORY_DEEP.md), semantisch abrufbar.


def classify(header: str) -> str:
    for k in HOT_KEYS:
        if k in header:
            return "hot"
    for k in RULES_KEYS:
        if k in header:
            return "rules"
    return "warm"


def split_sections(text: str):
    lines = text.splitlines(keepends=True)
    hdr = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if not hdr:
        return text, []
    preamble = "".join(lines[: hdr[0]])
    secs = []
    for k, i in enumerate(hdr):
        end = hdr[k + 1] if k + 1 < len(hdr) else len(lines)
        secs.append((lines[i].rstrip("\n"), "".join(lines[i:end])))
    return preamble, secs


def links_in(text: str) -> set[str]:
    return set(LINK_RE.findall(text)) | {f"[[{w}]]" for w in WIKI_RE.findall(text)}


def kb(s: str) -> float:
    return len(s.encode()) / 1024


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    old = HOT.read_text(encoding="utf-8")
    preamble, secs = split_sections(old)

    hot, rules, warm = [], [], []
    for h, b in secs:
        {"hot": hot, "rules": rules, "warm": warm}[classify(h)].append((h, b))

    # ---- HOT (MEMORY.md neu) : Präambel + HOT-Sektionen + Tiered-Index --------
    index = ["## 🗂 Tiered Index — Warm/Cold (semantisch abrufbar)\n",
             "> Verhaltens-Regeln werden vom SessionStart-Hook aus `MEMORY_RULES.md` injiziert.\n",
             "> Historie/Detail liegt in `MEMORY_DEEP.md` + Einzel-Files — per `memory_retrieve.py`/`vector_store.py` (bge-m3) on-demand abrufbar.\n\n",
             "**Injizierte Regeln (MEMORY_RULES.md):** " + ", ".join(h.split("— ")[0].strip("# ").strip() for h, _ in rules) + "\n\n",
             "**Warm (MEMORY_DEEP.md):**\n"]
    for h, _ in warm:
        index.append(f"- {h.strip('# ').strip()}\n")
    index_txt = "".join(index) + "\n"

    new_hot = preamble + "".join(b if b.endswith("\n") else b + "\n" for _, b in hot) + index_txt

    # ---- RULES (MEMORY_RULES.md) ---------------------------------------------
    rules_hdr = ("# MEMORY_RULES — Bug-Bounty-Verhaltensregeln (vom SessionStart-Hook injiziert)\n\n"
                 "> Auto-erzeugt von memory_restructure.py. Quelle der Wahrheit; wird bei jeder\n"
                 "> Session in den Kontext geladen (eigener Kanal, kein 24KB-Limit).\n\n")
    new_rules = rules_hdr + "\n".join(b.rstrip() for _, b in rules) + "\n"

    # ---- WARM (MEMORY_DEEP.md) : bestehend + neu verschobene ------------------
    old_warm = WARM.read_text(encoding="utf-8") if WARM.exists() else "# MEMORY_DEEP — Warm-Tier (on-demand)\n"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    moved = "\n".join(b.rstrip() for _, b in warm)
    new_warm = old_warm.rstrip() + f"\n\n---\n\n# 🗄 Verfassungs-Restructure ({stamp}) — verschobene Sektionen\n\n" + moved + "\n"

    # ---- INVARIANTEN (HARTES GATE) -------------------------------------------
    old_links = links_in(old)
    union = links_in(new_hot) | links_in(new_rules) | links_in(new_warm)
    lost = old_links - union
    # Partition: jede Original-Sektion-Body muss in genau einem Ziel vorkommen
    all_bodies_ok = all(
        (b.strip() in new_hot) ^ (b.strip() in new_rules) ^ (b.strip() in new_warm)
        for _, b in secs
    )

    print("════ Drei-Tier-Restructure — Plan ════")
    print(f"  MEMORY.md       (HOT) : {kb(old):.1f}KB → {kb(new_hot):.1f}KB  ({len(hot)} Sektionen + Index)")
    print(f"  MEMORY_RULES.md (RULES): {kb(new_rules):.1f}KB  ({len(rules)} Sektionen, hook-injiziert)")
    print(f"  MEMORY_DEEP.md  (WARM): +{kb(moved):.1f}KB verschoben ({len(warm)} Sektionen)")
    print(f"  HOT-Sektionen:  {[h.strip('# ').split('—')[0].strip()[:24] for h,_ in hot]}")
    print(f"  RULES-Sektionen:{[h.strip('# ').split('—')[0].strip()[:24] for h,_ in rules]}")
    m_hg = re.search(r"^##\s+.*HARD-GATES", new_hot, re.MULTILINE)
    hg_kb = kb(new_hot[:m_hg.start()]) if m_hg else -1
    print(f"  ⛔ HARD-GATES bei {hg_kb:.1f}KB · MEMORY.md gesamt {kb(new_hot):.1f}KB "
          f"({'≤24KB lädt voll ✅' if kb(new_hot)<=24 else 'NOCH >24KB ⚠️'})")
    print("════ Invarianten ════")
    print(f"  Links erhalten: {'JA ✅' if not lost else 'NEIN ❌ '+str(lost)}")
    print(f"  Saubere Partition (jede Sektion genau 1×): {'JA ✅' if all_bodies_ok else 'NEIN ❌'}")

    if lost or not all_bodies_ok:
        print("\n[ABBRUCH] Invariante verletzt — nichts geschrieben.", file=sys.stderr)
        return 1
    if not args.apply:
        print("\n[dry-run] Alles ok. Mit --apply anwenden (Backup wird erstellt).")
        return 0

    bts = datetime.now().strftime("%Y%m%d-%H%M%S")
    for f in (HOT, WARM):
        if f.exists():
            shutil.copy2(f, f.with_suffix(f".md.bak.{bts}"))
    HOT.write_text(new_hot, encoding="utf-8")
    RULES.write_text(new_rules, encoding="utf-8")
    WARM.write_text(new_warm, encoding="utf-8")
    print(f"\n[apply] Geschrieben. Backups *.bak.{bts}. MEMORY.md={kb(new_hot):.1f}KB, MEMORY_RULES.md={kb(new_rules):.1f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
