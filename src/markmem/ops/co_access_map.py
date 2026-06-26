#!/usr/bin/env python3
"""co_access_map.py — Hebbsche Co-Access-Karte aus metrics/access_log.jsonl.
Druckt die häufigsten Datei-Paare, die innerhalb eines Fensters zusammen gelesen
wurden. Lauf: python3 -m markmem.ops.co_access_map"""
from __future__ import annotations

import collections
import datetime
import json

from markmem import paths

AL = paths.ACCESS_LOG
WIN = datetime.timedelta(minutes=20)


def main() -> int:
    if not AL.exists():
        return 0
    ev = []
    for l in AL.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(l)
            p = d.get("path") or d.get("file") or ""
            n = p.split("/")[-1]
            ts = d.get("ts") or d.get("timestamp") or ""
            if n.endswith(".md") and ts:
                ev.append((datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")), n))
        except Exception:
            pass
    ev.sort()
    pair = collections.Counter()
    for i in range(len(ev)):
        for j in range(i + 1, len(ev)):
            if ev[j][0] - ev[i][0] > WIN:
                break
            if ev[i][1] != ev[j][1]:
                pair[tuple(sorted((ev[i][1], ev[j][1])))] += 1
    for (a, b), c in pair.most_common(30):
        if c >= 2:
            print(f"{c}\t{a}\t{b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
