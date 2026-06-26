#!/usr/bin/env python3
"""
update_memory_confidence.py — outcome backprop for cited memories.

When a submission resolves (won / lost / duplicate / informative),
walk the report file for [[wiki-links]] and feedback_*.md mentions,
and adjust the cited memories' frontmatter `confidence:` field accordingly.

Outcome deltas (additive, clamped to [0.0, 1.0]):
  won           : +0.10
  duplicate     : -0.05   (memory was not wrong, just outpaced)
  informative   : -0.15
  lost / na     : -0.20
  unknown       :  0.00   (just refresh last_verified)

Hard rules:
  - Default = DRY-RUN. --write to apply.
  - Always log to metrics/confidence_history.jsonl (append-only).
  - Never modify the report file itself.
  - Skip files without a `confidence:` field (don't fabricate one).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from markmem import paths

MEMORY_DIR = paths.MEMORY_DIR
METRICS_LOG = paths.CONFIDENCE_HISTORY

DELTAS = {
    "won": 0.10,
    "duplicate": -0.05,
    "informative": -0.15,
    "lost": -0.20,
    "na": -0.20,
    "unknown": 0.0,
}

WIKILINK_RE = re.compile(r"\[\[([a-zA-Z0-9_\-]+)\]\]")
MEMFILE_RE = re.compile(r"\b((?:feedback|project|reference|user)_[a-zA-Z0-9_\-]+\.md)\b")
CONFIDENCE_RE = re.compile(r"^(\s*confidence:\s*)([0-9.]+)\s*$", re.MULTILINE)
LASTVERIFIED_RE = re.compile(r"^(\s*last_verified:\s*).*$", re.MULTILINE)


def extract_citations(report_text: str) -> set[str]:
    """Return memory filenames cited in the report (resolves wiki-links + file references)."""
    cited_filenames: set[str] = set()

    # Direct file references
    for m in MEMFILE_RE.finditer(report_text):
        cited_filenames.add(m.group(1))

    # Wiki-links — resolve to filename
    wikilinks = set(WIKILINK_RE.findall(report_text))
    if not wikilinks:
        return cited_filenames

    # Build name → filename map from frontmatter
    name_to_file: dict[str, str] = {}
    norm_to_file: dict[str, str] = {}
    for path in MEMORY_DIR.glob("*.md"):
        if path.name == "MEMORY.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r"^name:\s*(\S+)\s*$", text, re.MULTILINE)
        if m:
            name_to_file[m.group(1)] = path.name
        norm_to_file[path.name[:-3].replace("_", "-")] = path.name

    for link in wikilinks:
        if link in name_to_file:
            cited_filenames.add(name_to_file[link])
        else:
            link_norm = link.replace("_", "-")
            if link_norm in norm_to_file:
                cited_filenames.add(norm_to_file[link_norm])

    return cited_filenames


def update_frontmatter(path: Path, delta: float, today: str) -> tuple[float, float] | None:
    """Return (old_conf, new_conf) or None if no confidence field to update."""
    text = path.read_text(encoding="utf-8")
    m = CONFIDENCE_RE.search(text)
    if not m:
        return None
    old = float(m.group(2))
    new = max(0.0, min(1.0, old + delta))
    new_text = CONFIDENCE_RE.sub(rf"\g<1>{new:.2f}", text, count=1)

    # Also bump last_verified (or add if missing under metadata)
    if LASTVERIFIED_RE.search(new_text):
        new_text = LASTVERIFIED_RE.sub(rf"\g<1>{today}", new_text, count=1)

    path.write_text(new_text)
    return (old, new)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-path", required=True, help="path to the report markdown file")
    ap.add_argument(
        "--outcome",
        required=True,
        choices=list(DELTAS.keys()),
        help="resolution outcome",
    )
    ap.add_argument("--write", action="store_true", help="apply changes (default = dry-run)")
    ap.add_argument(
        "--memory-slugs",
        nargs="*",
        help="restrict update to these slugs (else: all citations in report)",
    )
    ap.add_argument(
        "--submission-id",
        help="report-id (e.g. #3731389) — on --write, auto-acks it in confidence_loop so the outcome-loop self-clears",
    )
    args = ap.parse_args()

    report = Path(args.report_path)
    if not report.exists():
        print(f"[error] report not found: {report}", file=sys.stderr)
        return 1

    text = report.read_text(encoding="utf-8")
    cited = extract_citations(text)
    if args.memory_slugs:
        filter_set = set(args.memory_slugs)
        cited = {c for c in cited if c[:-3].replace("_", "-") in filter_set or c[:-3] in filter_set}

    if not cited:
        print(f"[info] no memory citations found in {report.name}")
        return 0

    delta = DELTAS[args.outcome]
    today = date.today().isoformat()
    changes = []
    skipped = []
    for fname in sorted(cited):
        target = MEMORY_DIR / fname
        if not target.exists():
            skipped.append((fname, "file not found"))
            continue
        if not args.write:
            text = target.read_text(encoding="utf-8")
            m = CONFIDENCE_RE.search(text)
            if not m:
                skipped.append((fname, "no confidence field"))
                continue
            old = float(m.group(2))
            new = max(0.0, min(1.0, old + delta))
            changes.append((fname, old, new))
        else:
            res = update_frontmatter(target, delta, today)
            if res is None:
                skipped.append((fname, "no confidence field"))
                continue
            changes.append((fname, res[0], res[1]))

    print(f"Report: {report.name}")
    print(f"Outcome: {args.outcome} (delta {delta:+.2f})")
    print(f"Cited memories: {len(cited)}")
    print()
    for fname, old, new in changes:
        marker = "WOULD" if not args.write else "DID"
        print(f"  {marker} update  {fname:60s}  {old:.2f} → {new:.2f}")
    for fname, reason in skipped:
        print(f"  skip          {fname:60s}  ({reason})")

    if args.write:
        METRICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with METRICS_LOG.open("a", encoding="utf-8") as f:
            for fname, old, new in changes:
                f.write(json.dumps({
                    "ts": datetime.now().isoformat(),
                    "report": str(report),
                    "outcome": args.outcome,
                    "delta": delta,
                    "memory": fname,
                    "old_confidence": old,
                    "new_confidence": new,
                }) + "\n")
        print(f"\n✓ Logged {len(changes)} updates to {METRICS_LOG}")
        # Auto-ack the submission so confidence_loop stops flagging it (loop self-clears)
        if args.submission_id:
            ack = paths.METRICS / "outcome_acked.txt"
            ack.parent.mkdir(parents=True, exist_ok=True)
            with ack.open("a", encoding="utf-8") as f:
                f.write(args.submission_id.strip() + "\n")
            print(f"✓ Auto-acked {args.submission_id} in outcome-loop")
    else:
        print("\n(dry-run — re-run with --write to apply)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
