#!/usr/bin/env python3
"""
confidence_loop.py — closes the outcome→confidence feedback loop.

The machinery exists (update_memory_confidence.py + /memory-outcome) but the
TRIGGER is manual, so resolved submissions silently never propagate their lesson
back to the cited memories' confidence. This detector closes that gap: it finds
submissions that are RESOLVED in the tracker but NOT yet propagated, and nudges.

It does NOT auto-apply confidence changes — outcome→confidence is behavior-
affecting and needs the human-verified report→memory mapping (/memory-outcome).
It only ensures the loop never stays silently open.

  --check    list resolved-but-unpropagated submissions (cron/banner surfacing)
  --ack ID   mark a submission handled (no citations / intentionally skipped)

"Handled" = its report-id appears in the ack ledger. /memory-outcome auto-acks
on --write (via update_memory_confidence.py --submission-id), so going forward
the loop self-clears; the existing backlog is acked once.

Pure stdlib, fail-open, no network.
"""
from __future__ import annotations

import argparse
import re
import sys

from markmem import paths

MEM = paths.MEMORY_DIR
TRACKER = MEM / "project_submission_tracker.md"
ACK_LEDGER = paths.METRICS / "outcome_acked.txt"

# A tracker row is "resolved" if its Status cell contains one of these.
RESOLVED_MARKERS = re.compile(
    r"(CLOSED|DUPLICATE|INFORMATIVE|N/A|\bNA\b|RESOLVED|WON|PAID|BOUNTY|OOS|RESOLVED)",
    re.IGNORECASE,
)
# Report-id: #1234567 (HackerOne) or AAAA-BBBB (Intigriti handle-id)
REPORT_ID = re.compile(r"#\d{6,}|[A-Z][A-Z0-9]{3,}-[A-Z0-9]{4,}")
# An unresolved row should NOT be flagged
OPEN_MARKERS = re.compile(r"(AWAITING|TRIAGE|OPEN|PENDING|IN[ -]?FLIGHT|wartet)", re.IGNORECASE)


def load_acked() -> set[str]:
    if not ACK_LEDGER.exists():
        return set()
    try:
        # NB: report-ids start with '#' (e.g. #3629933) — only '# ' (hash+space) is a comment.
        return {l.strip() for l in ACK_LEDGER.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("# ")}
    except Exception:
        return set()


def parse_tracker() -> list[dict]:
    """Return resolved submissions: [{id, outcome, row}]."""
    if not TRACKER.exists():
        return []
    out = []
    seen: set[str] = set()
    try:
        lines = TRACKER.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    # Nur die "Eingereichte Reports"-Sektion parsen — verhindert False-Positives
    # aus Planungs-/EV-Tabellen (z.B. TEST-XXXX-Sandbox-Token-Platzhalter).
    in_section = False
    for line in lines:
        if line.startswith("## "):
            in_section = "Eingereichte Reports" in line
            continue
        if not in_section:
            continue
        if not line.startswith("|") or line.count("|") < 5:
            continue
        if OPEN_MARKERS.search(line) and not RESOLVED_MARKERS.search(line):
            continue
        if not RESOLVED_MARKERS.search(line):
            continue
        m = REPORT_ID.search(line)
        if not m:
            continue
        rid = m.group(0)
        if rid in seen:
            continue
        seen.add(rid)
        # crude outcome tag from the status text
        status = line.upper()
        if "DUPLICATE" in status:
            outcome = "duplicate"
        elif "INFORMATIVE" in status:
            outcome = "informative"
        elif "N/A" in status or "OOS" in status:
            outcome = "na"
        elif "WON" in status or "PAID" in status or "BOUNTY" in status:
            outcome = "won"
        else:
            outcome = "closed"
        out.append({"id": rid, "outcome": outcome})
    return out


def check() -> dict:
    """Return {'pending': [...], 'acked': N, 'resolved': N}."""
    resolved = parse_tracker()
    acked = load_acked()
    pending = [r for r in resolved if r["id"] not in acked]
    return {"pending": pending, "acked": len(acked), "resolved": len(resolved)}


def main() -> int:
    try:
        ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        g = ap.add_mutually_exclusive_group(required=True)
        g.add_argument("--check", action="store_true", help="list resolved-but-unpropagated submissions")
        g.add_argument("--ack", nargs="+", metavar="ID", help="mark submission(s) handled")
        args = ap.parse_args()

        if args.ack:
            ACK_LEDGER.parent.mkdir(parents=True, exist_ok=True)
            with ACK_LEDGER.open("a", encoding="utf-8") as f:
                for rid in args.ack:
                    f.write(rid.strip() + "\n")
            print(f"Acked: {', '.join(args.ack)}")
            return 0

        res = check()
        pend = res["pending"]
        print(f"Resolved submissions: {res['resolved']} · acked/propagated: {res['acked']} · pending: {len(pend)}")
        print(f"PENDING_OUTCOMES={len(pend)}")
        if pend:
            print("\nResolved but confidence NOT yet propagated — run /memory-outcome <report> "
                  "(or `confidence_loop.py --ack <id>` if no citations):")
            for p in pend:
                print(f"  {p['id']:24s} outcome={p['outcome']}")
        return 0
    except Exception:
        pass  # fail-open
    return 0


if __name__ == "__main__":
    sys.exit(main())
