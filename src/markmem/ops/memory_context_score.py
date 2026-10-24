#!/usr/bin/env python3
"""
memory_context_score.py — outcome-graded memory-quality grader.

Rates memories from ACTUAL usage rather than age: a join of metrics/access_log.jsonl
(which files were really pulled via Read) x token cost x age. Result: DEAD-WEIGHT
candidates (expensive, never used, old) for the archive vs. LOAD-BEARING (used often).
Fills the retire decision with data.

Advisory, read-only, deletes/blocks NOTHING. "Never read" != "useless": excluded are
(a) INJECTED rule files (MEMORY_RULES.md -- used via context injection, not via Read),
(b) FRESH files (< FRESH_DAYS -- no time to be used yet), (c) the MEMORY* index files.
Hard-gate memories are legitimately rarely pulled -> a candidate means REVIEW, not delete.
A human decides.

Complement to memory_audit.py (stale-by-date); this is dead-by-usage. stdlib-only.
`--top N`, `--json`, `--min-tokens N`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from markmem import paths

MEM = paths.MEMORY_DIR
ACCESS_LOG = paths.ACCESS_LOG
INDEXES = [paths.INDEX_FILE.name, paths.DEEP_FILE.name, paths.INFRA_FILE.name]
RULES_NAME = paths.RULES_FILE.name
FRESH_DAYS = 14          # younger = too new to judge
OLD_DAYS = 30            # older + unused = candidate
LOAD_BEARING = 3         # >= N accesses = load-bearing (keep)


def _now():
    return datetime.now(timezone.utc)


def load_access():
    """file -> (count, last_access_datetime). Fail-open on an empty/missing log."""
    counts, last = Counter(), {}
    if not ACCESS_LOG.exists():
        return counts, last
    for raw in ACCESS_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
            f = Path(e.get("file", "")).name
            if not f:
                continue
            counts[f] += 1
            ts = e.get("ts")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if f not in last or dt > last[f]:
                        last[f] = dt
                except Exception:
                    pass
        except Exception:
            continue
    return counts, last


def _linked(files):
    """All .md names linked from the given index/rules files."""
    out = set()
    for fn in files:
        p = MEM / fn
        if p.exists():
            for m in re.finditer(r"\(([\w./-]+\.md)\)", p.read_text(encoding="utf-8", errors="replace")):
                out.add(Path(m.group(1)).name)
    return out


def injected_files():
    """Linked from MEMORY_RULES.md (content used without a Read) -> never dead-weight."""
    return _linked([RULES_NAME])


def indexed_files():
    """Linked from the MEMORY* indexes: the index LINE carries the signal, detail is cold-on-demand."""
    return _linked(INDEXES)


def grade(min_tokens=0):
    counts, last = load_access()
    injected = injected_files()
    indexed = indexed_files()
    now = _now()
    rows = []
    for p in sorted(MEM.glob("*.md")):
        name = p.name
        if name.startswith("MEMORY"):          # index/injected aggregate files themselves: don't grade
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
            tokens = len(txt) // 4
            age_days = (now - datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)).days
        except Exception:
            continue
        acc = counts.get(name, 0)
        last_days = (now - last[name]).days if name in last else None
        if name in injected:
            cls = "injected"                    # used via rules, not via Read
        elif acc >= LOAD_BEARING:
            cls = "load-bearing"
        elif age_days < FRESH_DAYS:
            cls = "fresh"                        # too new to judge
        elif acc == 0 and age_days >= OLD_DAYS and name in indexed:
            cls = "indexed-cold"                 # index line carries the signal; detail = cold backup (not an orphan)
        elif acc == 0 and age_days >= OLD_DAYS:
            cls = "dead-weight"                  # ORPHAN: not indexed, not injected, old, never pulled
        elif acc <= 2:
            cls = "low-use"
        else:
            cls = "ok"
        rows.append({"file": name, "tokens": tokens, "accesses": acc,
                     "last_access_days": last_days, "age_days": age_days, "class": cls})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Outcome-graded memory-quality grader (read-only, advisory).")
    ap.add_argument("--top", type=int, default=20, help="top-N dead-weight candidates (default 20)")
    ap.add_argument("--min-tokens", type=int, default=200, help="dead-weight only from N tokens (noise filter)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = grade()
    by = Counter(r["class"] for r in rows)
    total_tok = sum(r["tokens"] for r in rows)
    dead = sorted([r for r in rows if r["class"] == "dead-weight" and r["tokens"] >= args.min_tokens],
                  key=lambda r: -r["tokens"])
    dead_tok = sum(r["tokens"] for r in dead)
    icold = sorted([r for r in rows if r["class"] == "indexed-cold" and r["tokens"] >= args.min_tokens],
                   key=lambda r: -r["tokens"])
    load = sorted([r for r in rows if r["class"] == "load-bearing"], key=lambda r: -r["accesses"])

    if args.json:
        print(json.dumps({"summary": {"files": len(rows), "total_tokens": total_tok,
                          "classes": dict(by), "dead_weight_tokens": dead_tok},
                          "dead_weight": dead, "indexed_cold": icold, "load_bearing": load[:15]},
                          ensure_ascii=False, indent=2))
        return 0

    print("+- memory context-score -- outcome-graded quality (read-only, NO auto-delete) -+")
    print(f"| {len(rows)} memory files - ~{total_tok:,} token-tax - classes: "
          + " - ".join(f"{k}={v}" for k, v in by.most_common()))
    print(f"| dead-weight candidates (>{args.min_tokens} tok): {len(dead)} files ~= ~{dead_tok:,} tokens recoverable")
    print("| note: 'never read' != useless -- injected rules / fresh / hard-gates are excluded or legitimately rare.")
    print("|       candidates = REVIEW (-> _archive/), not a kill list. Access = Read tool only.")
    print("+" + "-" * 78 + "+")
    if dead:
        print(f"\nDEAD-WEIGHT (old >{OLD_DAYS}d, 0 accesses, not injected) -- top {min(args.top, len(dead))}:")
        for r in dead[:args.top]:
            print(f"   ~{r['tokens']:>4} tok - {r['age_days']:>4}d old - {r['file']}")
    if icold:
        print(f"\nINDEXED-COLD ({len(icold)} files, >{args.min_tokens} tok) -- linked in an index but never read:")
        print("   the index line works; the detail is a cold backup. Archive the detail OR trim the index line.")
        for r in icold[:8]:
            print(f"   ~{r['tokens']:>4} tok - {r['file']}")
    if load:
        print(f"\nLOAD-BEARING (>={LOAD_BEARING} accesses) -- top 8 (keep, maybe warm-tier):")
        for r in load[:8]:
            print(f"   {r['accesses']:>3}x - {r['file']}")
    print("\n-> full data: --json  -  the archive decision is the user's (HITL)  -  vs memory_audit.py = stale-by-date")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"memory_context_score: error (read-only, nothing changed): {e}", file=sys.stderr)
        sys.exit(0)
