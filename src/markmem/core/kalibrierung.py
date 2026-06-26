#!/usr/bin/env python3
"""
kalibrierung.py — Kalibrierungs-Messung (Gedächtnis-v3 Lern-Schicht, Bauplan v2 Teil 14.3).

"Der Schutz vor mir selbst": der gefährlichste Fehler ist nicht Unwissen, sondern
zu sicher zu klingen, wenn ich rate. Dieser Baustein macht das messbar — NICHT als
Note für mich, sondern als Werkzeug, das sagt, WO der User mir misstrauen / wo ich
gegenchecken sollte.

Signal: metrics/confidence_history.jsonl (von update_memory_confidence.py / outcomes).
Pro Memory das Netto-Delta aufsummieren. Stark negativ = die Karte wurde in
aufgelösten Submissions zitiert, die NICHT gewonnen haben (lost/dup/informative)
= ihr „Rat" trug nicht. Solche Karten bekommen einen Verify-Marker.

Output: metrics/kalibrierung.json (+ optional menschenlesbarer Digest).
Read-only Analyse, schreibt nur Metrik/Digest. Kein LLM, kein Netz.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

from markmem import paths

HIST = paths.CONFIDENCE_HISTORY
OUT = paths.KALIB_FILE

MISCAL_THRESHOLD = -0.20  # Netto-Delta ≤ -0.2 → "Selbstvertrauen trog hier"


def compute() -> dict:
    if not HIST.exists():
        return {"memories": {}, "miscalibrated": []}
    agg: dict[str, dict] = defaultdict(lambda: {"net": 0.0, "events": 0, "cases": set()})
    for line in HIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        mem = e.get("memory")
        if not mem:
            continue
        a = agg[mem]
        a["net"] += float(e.get("delta", 0.0))
        a["events"] += 1
        if e.get("case"):
            a["cases"].add(e["case"])
    memories = {m: {"net": round(v["net"], 3), "events": v["events"], "cases": sorted(v["cases"])}
                for m, v in agg.items()}
    miscal = sorted(
        ({"memory": m, **d} for m, d in memories.items() if d["net"] <= MISCAL_THRESHOLD),
        key=lambda x: x["net"],
    )
    return {"memories": memories, "miscalibrated": miscal}


def main() -> int:
    quiet = "--quiet" in sys.argv
    res = compute()
    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    mis = res["miscalibrated"]
    if not quiet:
        print(f"[done] Kalibrierung → {OUT}")
        if not mis:
            print("  Keine miskalibrierten Karten (Netto-Delta > -0.2).")
        else:
            print(f"  ⚠ {len(mis)} Karte(n) wo Selbstvertrauen trog (vor Zitat gegenchecken):")
            for m in mis[:10]:
                print(f"    {m['net']:+.2f}  {m['memory']}  ({m['events']} Outcomes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
