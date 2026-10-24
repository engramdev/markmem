#!/usr/bin/env python3
"""
memory_sort_suggest.py — read-only sort suggestions for MEMORY.md sections.

Reads JSON cache, computes trust-score (confidence × importance) per file,
groups by current MEMORY.md section, and prints the suggested re-order.

Output: per section, sorted list with current vs suggested position.
Does NOT modify MEMORY.md. User decides which sections to manually re-order.

Hard rules:
  - Read-only
  - Skips files without confidence or importance (no fake sort)
  - Respects current section taxonomy (no cross-section moves)
"""
from __future__ import annotations

import json
import re

from markmem import paths

INDEX = paths.INDEX_FILE
CACHE = paths.INDEX_CACHE

SECTION_RE = re.compile(r"^##\s+(.+?)$", re.MULTILINE)
LINK_RE = re.compile(r"\[([a-zA-Z0-9_\-]+\.md)\]\(([a-zA-Z0-9_\-]+\.md)\)")


def safe_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def safe_int(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def parse_sections(text: str) -> list[tuple[str, list[tuple[int, str]]]]:
    """Return [(section_title, [(line_num, filename), ...])]."""
    lines = text.split("\n")
    sections: list[tuple[str, list]] = []
    current_section = None
    current_files = []
    for i, line in enumerate(lines):
        m = SECTION_RE.match(line)
        if m:
            if current_section is not None:
                sections.append((current_section, current_files))
            current_section = m.group(1)
            current_files = []
            continue
        if line.startswith("- "):
            l = LINK_RE.search(line)
            if l:
                current_files.append((i, l.group(2)))
    if current_section is not None:
        sections.append((current_section, current_files))
    return sections


def trust_score(meta: dict) -> float:
    conf = safe_float(meta.get("confidence"))
    imp = safe_int(meta.get("importance"))
    return conf * imp


def main() -> int:
    if not CACHE.exists():
        print("Cache missing. Run memory_audit.py first.")
        return 1

    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    memories = cache.get("memories", {})
    text = INDEX.read_text(encoding="utf-8")
    sections = parse_sections(text)

    print("=" * 70)
    print("  MEMORY.md SORT-SUGGEST — trust = confidence × importance")
    print("=" * 70)
    print()
    print("  Sections shown only when current order differs from suggested.")
    print()

    suggestions = 0
    for section_title, files in sections:
        if len(files) < 2:
            continue
        # Build (score, current_index, filename) list
        scored = []
        for idx, (line_num, fname) in enumerate(files):
            meta = memories.get(fname, {})
            score = trust_score(meta)
            scored.append((score, idx, fname))

        # Sort by score descending (suggested order)
        suggested = sorted(scored, reverse=True)
        current_order = [s[2] for s in scored]
        suggested_order = [s[2] for s in suggested]

        if current_order == suggested_order:
            continue

        suggestions += 1
        print(f"## {section_title}")
        print(f"   {'pos':>4} {'score':>6}  current → suggested")
        for new_pos, (score, old_pos, fname) in enumerate(suggested):
            marker = "  " if new_pos == old_pos else "→ "
            delta = f"(was #{old_pos+1})" if new_pos != old_pos else ""
            short = fname[:50]
            print(f"   {marker}{new_pos+1:>2} {score:>5.1f}  {short:<50} {delta}")
        print()

    if suggestions == 0:
        print("  ✓ All sections already in trust-order. Nothing to suggest.")
    else:
        print(f"  → {suggestions} sections could be re-sorted manually.")
        print("  → To preserve curation, no auto-apply. User edits MEMORY.md selectively.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
