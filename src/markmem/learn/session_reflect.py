#!/usr/bin/env python3
"""
session_reflect.py — SessionEnd hook.

Writes a structured digest of the session to sessions/YYYY-MM-DD-<short-id>.md.
This is the "recall tier" (MemGPT) — not loaded into context, searchable on demand.

Does NOT propose memories directly. The /memory-review command later mines
digests + surprises + user input to interactively produce memory proposals
(Human-in-the-Loop). This separation prevents hallucinated memories.

Hard guarantees:
  - Append-only writes (one file per session).
  - Fail-open: any error → exit 0.
  - Capped CPU: reads at most last 2 MB of transcript.
  - No network, no LLM, < 500ms typical.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from markmem import paths

SESSIONS_DIR = paths.MEMORY_DIR / "sessions"
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024  # 2 MB cap

# Surprise patterns from surprise_catcher.py — keep in sync
SURPRISE_PATTERNS = [
    r"\b(falsch|wrong|incorrect|fehler|mistake)\b",
    r"\b(stop|stopp|halt|abbrechen)\b",
    r"\b(nein|no,)\b",
    r"\b(vergessen|forgot|missing|verpasst)\b",
    r"\b(genau|exactly|perfect|perfekt|good call)\b",
]


def tail_read(path: Path, max_bytes: int) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            # discard partial first line
            f.readline()
        return f.read().decode("utf-8", errors="replace")


def extract_jsonl_entries(text: str) -> list[dict]:
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summarize(entries: list[dict]) -> dict:
    user_msgs: list[str] = []
    tools: Counter[str] = Counter()
    files_written: list[str] = []
    files_read: list[str] = []
    bash_cmds: list[str] = []
    errors = 0

    for e in entries:
        msg = e.get("message") or e
        role = msg.get("role")
        if role == "user":
            content = msg.get("content")
            if isinstance(content, str):
                user_msgs.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        user_msgs.append(part.get("text", ""))

        # Tool use blocks
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    tname = part.get("name", "?")
                    tools[tname] += 1
                    inp = part.get("input", {})
                    if tname == "Write":
                        files_written.append(inp.get("file_path", "?"))
                    elif tname == "Read":
                        files_read.append(inp.get("file_path", "?"))
                    elif tname == "Bash":
                        cmd = inp.get("command", "")[:120]
                        bash_cmds.append(cmd)
                elif part.get("type") == "tool_result" and part.get("is_error"):
                    errors += 1

    surprises = []
    for u in user_msgs:
        for pat in SURPRISE_PATTERNS:
            m = re.search(pat, u, re.IGNORECASE)
            if m:
                excerpt = u.strip()
                if len(excerpt) > 200:
                    excerpt = excerpt[:200] + "..."
                surprises.append((m.group(0), excerpt))
                break

    return {
        "user_turn_count": len(user_msgs),
        "tools": dict(tools.most_common()),
        "tool_errors": errors,
        "files_written": sorted(set(files_written))[:20],
        "files_read_count": len(set(files_read)),
        "bash_sample": bash_cmds[:5],
        "surprises": surprises,
    }


def citation_metrics(transcript_path: str) -> dict | None:
    """Call the citation analyzer for the current transcript. Lightweight, JSON output."""
    if not transcript_path:
        return None
    import subprocess
    try:
        out = subprocess.run(
            [sys.executable, "-m", "markmem.ops.citation_analyzer", transcript_path, "--json-only"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout)
    except Exception:
        pass
    return None


def session_summary_for_humans(s: dict, session_id: str, started_at: str | None, citation: dict | None = None) -> str:
    lines = ["---"]
    lines.append(f"session_id: {session_id}")
    lines.append(f"ended_at: {datetime.now().isoformat()}")
    if started_at:
        lines.append(f"started_at: {started_at}")
    lines.append(f"user_turns: {s['user_turn_count']}")
    lines.append(f"tool_errors: {s['tool_errors']}")
    lines.append(f"surprise_count: {len(s['surprises'])}")
    lines.append("---\n")

    lines.append("## Tools used\n")
    if s["tools"]:
        for t, n in s["tools"].items():
            lines.append(f"- {t}: {n}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Files written\n")
    if s["files_written"]:
        for f in s["files_written"]:
            lines.append(f"- {f}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Files read\n")
    lines.append(f"{s['files_read_count']} distinct files\n")

    lines.append("## Bash sample (first 5)\n")
    for c in s["bash_sample"]:
        lines.append(f"- `{c}`")
    if not s["bash_sample"]:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Surprises detected\n")
    if s["surprises"]:
        for trigger, excerpt in s["surprises"]:
            lines.append(f"- **{trigger}**: > {excerpt}")
    else:
        lines.append("- (none — review surprises.md if any were missed)")
    lines.append("")

    lines.append("## Memory-review hints\n")
    lines.append("Run `/memory-review` to interactively decide if any of the above warrant a permanent memory.\n")

    if citation:
        rate = citation.get("citation_rate", 0)
        marker = "✓" if rate >= 0.7 else ("⚠" if rate >= 0.4 else "✗")
        lines.append(f"\n## Citation-discipline {marker}")
        lines.append(f"- Advice turns: {citation.get('advice_turns', 0)}")
        lines.append(f"- Cited turns: {citation.get('cited_turns', 0)}")
        lines.append(f"- Citation rate: {rate:.0%}")
        lines.append(f"- Misses this session: {citation.get('miss_count', 0)}")
        if rate < 0.5:
            lines.append("- ⚠ Below target (≥70%) — review inbox/citation_misses.md")

    return "\n".join(lines)


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return 0

        session_id = data.get("session_id", "unknown")
        short = session_id.split("-")[0][:8] if session_id != "unknown" else "unknown"
        transcript_path = data.get("transcript_path")

        if not transcript_path or not os.path.exists(transcript_path):
            # Still write a minimal stub so we know the session ran
            text = ""
        else:
            text = tail_read(Path(transcript_path), MAX_TRANSCRIPT_BYTES)

        entries = extract_jsonl_entries(text) if text else []
        summary = summarize(entries)
        citation = citation_metrics(transcript_path) if transcript_path else None

        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        path = SESSIONS_DIR / f"{today}-{short}.md"

        # If file exists (same session re-entered or duplicate end), append rather than overwrite
        content = session_summary_for_humans(summary, session_id, data.get("started_at"), citation)
        if path.exists():
            content = f"\n\n<!-- re-emitted at {datetime.now().isoformat()} -->\n\n" + content
            with path.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            path.write_text(content)

        # Korrektur-Synapse: snapshot der von Claude editierten Dateien (Bauplan 14.1).
        # In diesen bereits-registrierten SessionEnd-Hook integriert (kein neuer Hook).
        # Optional: das Modul kommt separat in integrations/ — fehlt es, kein Fehler.
        # Fail-open: ein Fehler hier darf das Digest nicht gefährden.
        try:
            from markmem.integrations import correction_synapse
            correction_synapse.capture(transcript_path or "", session_id)
        except Exception:
            pass
    except Exception:
        pass  # fail-open
    return 0


if __name__ == "__main__":
    sys.exit(main())
