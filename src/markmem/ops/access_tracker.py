#!/usr/bin/env python3
"""
access_tracker.py — PostToolUse hook for memory access analytics.

Fires after Read tool calls. If the read path is under memory/,
appends a JSONL entry to metrics/access_log.jsonl.

Used by audit/quiz to flag never-read memories as archive candidates.

Hard rules:
  - Fail-open: any error → exit 0
  - Silent: no stdout/stderr
  - Bounded: < 50ms typical, atomic append (no locking needed for single-user)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

from markmem import paths

MEMORY_DIR = str(paths.MEMORY_DIR)
LOG = paths.ACCESS_LOG


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return 0

        tool_name = data.get("tool_name", "")
        if tool_name != "Read":
            return 0

        tool_input = data.get("tool_input", {}) or {}
        path = tool_input.get("file_path", "")
        if not path.startswith(MEMORY_DIR):
            return 0

        # Skip our own metadata files (would create feedback loop)
        if "/metrics/" in path or "/inbox/" in path or "/sessions/" in path:
            return 0

        # Skip index files (they're loaded every session, would dwarf real signals)
        name = path.rsplit("/", 1)[-1]
        if name in ("MEMORY.md", "MEMORY_DEEP.md"):
            return 0

        session_id = data.get("session_id", "?")[:8]
        entry = {
            "ts": datetime.now().isoformat(),
            "file": name,
            "session": session_id,
        }
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
