#!/usr/bin/env python3
"""
find_target_feedbacks.py — collect all feedback_<target>_*.md for a given target.

Used by /memory-stub to auto-build project_<target>_*.md skeleton from
the feedback files the user already created.

Output: JSON with feedback file metadata (path, description, wikilinks).
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from markmem import paths

MEMORY_DIR = paths.MEMORY_DIR
DESC_RE = re.compile(r"^description:\s*(.+?)$", re.MULTILINE)
NAME_RE = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="target name (e.g. notion, mollie, rivian)")
    args = ap.parse_args()

    target = args.target.lower()
    # Match: feedback_<target>_..., feedback_<target>-...
    pattern = re.compile(rf"^feedback_{re.escape(target)}[_\-]", re.IGNORECASE)

    matches = []
    for path in sorted(MEMORY_DIR.glob("feedback_*.md")):
        if not pattern.match(path.name):
            continue
        text = path.read_text(encoding="utf-8")
        desc = DESC_RE.search(text)
        name = NAME_RE.search(text)
        matches.append({
            "file": path.name,
            "slug": name.group(1) if name else path.name[:-3].replace("_", "-"),
            "description": (desc.group(1).strip().strip('"').strip("'") if desc else ""),
            "lines": len(text.splitlines()),
        })

    if not matches:
        print(f"[warn] no feedback_*{target}*.md files found", file=sys.stderr)
        return 1

    print(json.dumps({"target": target, "matches": matches}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
