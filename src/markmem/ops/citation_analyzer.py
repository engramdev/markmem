#!/usr/bin/env python3
"""
citation_analyzer.py — analyze how well Claude cited memory files in a transcript.

For each assistant turn:
  1. Heuristic: was this an "advice" response that should have cited memories? (keyword + length)
  2. If yes: did it include at least one [[wiki-link]] or feedback_X.md / project_X.md reference?
  3. Compute citation_rate = cited_responses / advice_responses

Output:
  - JSON metrics (stdout if --json-only)
  - Human report (stdout default)
  - Optional: write misses to inbox/citation_misses.md (--write-inbox)

This is feedback-only — no enforcement. Goal: surface my own discipline pattern.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from markmem import paths

MEMORY_DIR = paths.MEMORY_DIR
INBOX_FILE = paths.INBOX / "citation_misses.md"

# Heuristic: is this an "advice" response that should have cited memories?
ADVICE_KEYWORDS = re.compile(
    r"\b(submit|scope|bounty|recon|hypothes|poc|vuln|exploit|payload|"
    r"informative|duplicate|hard-gate|memory|hacktivity|cvss|"
    r"OOB|SSRF|XSS|BOLA|IDOR|RCE|SQLi|jwks|oauth|jwt|"
    r"endpoint|api|fuzz|nuclei|burp|caido|intigriti|hackerone)\b",
    re.IGNORECASE,
)

CITATION_PATTERNS = [
    re.compile(r"\[\[[a-zA-Z0-9_\-]+\]\]"),  # [[wiki-link]]
    re.compile(r"\b(feedback|project|reference|user)_[a-zA-Z0-9_\-]+\.md\b"),  # file ref
]

MIN_ADVICE_WORDS = 50  # below this = casual reply, not advice


def is_advice(text: str) -> bool:
    if len(text.split()) < MIN_ADVICE_WORDS:
        return False
    matches = len(ADVICE_KEYWORDS.findall(text))
    return matches >= 3  # at least 3 BB-related keywords


def has_citation(text: str) -> tuple[int, list[str]]:
    found = []
    for pat in CITATION_PATTERNS:
        for m in pat.finditer(text):
            found.append(m.group(0))
    return len(found), found


def iter_assistant_turns(transcript_path: Path):
    """Yield (timestamp, text) for each assistant text turn in a JSONL transcript."""
    if not transcript_path.exists():
        return
    with transcript_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = entry.get("message") or entry
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "assistant":
                continue
            ts = entry.get("timestamp", "")
            content = msg.get("content", "")
            if isinstance(content, str):
                if content.strip():
                    yield ts, content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text", "")
                        if text.strip():
                            yield ts, text


def analyze(transcript_path: Path) -> dict:
    advice_turns = []
    cited_turns = []
    misses = []  # (ts, excerpt)
    for ts, text in iter_assistant_turns(transcript_path):
        if not is_advice(text):
            continue
        advice_turns.append((ts, text))
        n_cites, found = has_citation(text)
        if n_cites > 0:
            cited_turns.append((ts, n_cites, found[:3]))
        else:
            excerpt = text[:200].replace("\n", " ").strip()
            misses.append((ts, excerpt))
    total = len(advice_turns)
    cited = len(cited_turns)
    rate = (cited / total) if total else 0
    return {
        "transcript": str(transcript_path),
        "total_assistant_turns": sum(1 for _ in iter_assistant_turns(transcript_path)),
        "advice_turns": total,
        "cited_turns": cited,
        "misses": misses,
        "citation_rate": round(rate, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("transcript", help="path to JSONL transcript")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--write-inbox", action="store_true",
                    help="append misses to inbox/citation_misses.md")
    args = ap.parse_args()

    result = analyze(Path(args.transcript))

    if args.json_only:
        # Slim version for embedding in session digest
        out = {k: v for k, v in result.items() if k != "misses"}
        out["miss_count"] = len(result["misses"])
        print(json.dumps(out))
        return 0

    # Human report
    print("=" * 64)
    print("CITATION-DISCIPLINE ANALYSIS")
    print("=" * 64)
    print(f"Transcript: {result['transcript']}")
    print(f"Total assistant turns: {result['total_assistant_turns']}")
    print(f"Advice turns (≥{MIN_ADVICE_WORDS} words, ≥3 BB-keywords): {result['advice_turns']}")
    print(f"Cited turns ([[link]] or .md ref): {result['cited_turns']}")
    print(f"Citation rate: {result['citation_rate']:.0%}")
    print()
    if result["misses"]:
        print(f"Misses ({len(result['misses'])}):")
        for ts, excerpt in result["misses"][:10]:
            print(f"  [{ts[:19]}] {excerpt[:120]}{'...' if len(excerpt) > 120 else ''}")
        if len(result["misses"]) > 10:
            print(f"  ... +{len(result['misses']) - 10} more")
    else:
        print("✓ No misses — every advice turn carried at least one citation.")

    if args.write_inbox and result["misses"]:
        INBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        with INBOX_FILE.open("a", encoding="utf-8") as f:
            f.write(f"\n## {ts} — citation rate {result['citation_rate']:.0%} ({result['cited_turns']}/{result['advice_turns']})\n")
            f.write(f"Transcript: `{result['transcript']}`\n\n")
            for t, excerpt in result["misses"][:10]:
                f.write(f"- [{t[:19]}] {excerpt[:200]}\n")
        print(f"\n[inbox] appended to {INBOX_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
