#!/usr/bin/env python3
"""
surprise_catcher.py — UserPromptSubmit hook.

Highest-EV learning signal per Reflexion (Shinn et al. 2023): user corrections.
When the user says "no", "wrong", "you forgot X", etc. — capture it for later review.

Behavior:
  - Silent on success (no stdout/stderr): hook must not inject context.
  - Fail-open: any error → exit 0. Never block user prompt.
  - Append-only write to inbox/surprises.md.
  - Lightweight pattern match — no LLM, no network, < 50ms typical.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime

from markmem import paths

INBOX = paths.INBOX / "surprises.md"

# Multi-language correction signals (DE + EN, weighted by specificity)
# Each pattern must be a *word-boundary* match to avoid false positives.
PATTERNS = [
    # Strong corrections
    (r"\b(falsch|wrong|incorrect|fehler|mistake)\b", "correction"),
    (r"\b(stop|stopp|halt|abbrechen)\b", "halt"),
    (r"\b(nein|no,)\b", "denial"),
    (r"\b(vergessen|forgot|missing|verpasst)\b", "omission"),
    (r"\b(übersehen|missed|overlooked)\b", "oversight"),
    # Pattern-level feedback
    (r"\b(nicht so|don'?t do|stop doing)\b", "anti-pattern"),
    (r"\b(immer|always|nie|never)\b.{0,40}\b(machen|do|sein|be)\b", "rule-creation"),
    # Confirmations of non-obvious choices (also valuable — Generative Agents)
    (r"\b(genau|exactly|perfect|perfekt|good call)\b", "positive-confirmation"),
]

# Tags that, ALONE, carry no behavioral lesson — see surprise_triage.py.
# Upstream precision fix: don't capture a prompt whose only signal is weak.
WEAK_TAGS_ONLY = {"positive-confirmation", "halt"}

# Content that fires a keyword tag but is provably not a lesson for Claude.
# Mirrors the noise classes in surprise_triage.py so the inbox stays clean
# at the source instead of relying solely on downstream triage.
NOISE_CONTENT = [
    re.compile(r"^\s*#\s*(auftrag|klärung|ziel\b|aufgabe)", re.IGNORECASE),  # task brief
    re.compile(r"(multiple commands produce|build input files cannot be found"
               r"|has no member|no such module|\.swift:\d+:\d+|deriveddata"
               r"|linker command failed|undefined symbol)", re.IGNORECASE),   # build error
    re.compile(r"(╭─|╰─|✔ ─╮|pbpaste|pbcopy)"),                               # terminal paste
    re.compile(r"^\s*(was jetzt|was soll ich|was nun|wie weiter|wo (soll|steh"
               r"|ist)|ich bin am (mac|amc)|was denkst du|was hältst du"
               r"|erkläre mir|gib mir)", re.IGNORECASE),                       # direction/opinion
]

# Skip prompts that are likely not corrections (avoid noise)
# Anchored patterns (match at start)
SKIP_HINTS = [
    r"^\s*(ls|cd|cat|grep|find|git)\s",  # raw shell commands
    r"^\s*/",  # slash commands
    r"^\s*\?$",  # just "?"
]
# Substring patterns (skip if found ANYWHERE — these are system-injected, not user input)
SKIP_IF_CONTAINS = [
    "<task-notification>",
    "<system-reminder>",
    "<command-name>",
    "<command-message>",
    "<tool-use-id>",
    "<output-file>",
    "<status>",
    "[SYSTEM NOTIFICATION",
]


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return 0
        prompt = (data.get("prompt") or "").strip()
        if not prompt or len(prompt) < 3:
            return 0
        if any(re.match(p, prompt, re.IGNORECASE) for p in SKIP_HINTS):
            return 0
        if any(tag in prompt for tag in SKIP_IF_CONTAINS):
            return 0

        # Score the prompt against patterns
        hits = []
        lower = prompt.lower()
        for pattern, tag in PATTERNS:
            if re.search(pattern, lower, re.IGNORECASE):
                hits.append(tag)
        if not hits:
            return 0

        # Upstream precision filters (mirror surprise_triage.py noise classes):
        # 1. drop prompts whose only signal is weak (pure confirmation / halt)
        if set(hits).issubset(WEAK_TAGS_ONLY):
            return 0
        # 2. drop content that is provably not a behavioral lesson
        if any(rx.search(prompt) for rx in NOISE_CONTENT):
            return 0

        session_id = data.get("session_id", "unknown")[:8]
        cwd = data.get("cwd", "?")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        excerpt = prompt if len(prompt) <= 240 else prompt[:237] + "..."
        excerpt = excerpt.replace("\n", " ⏎ ")

        entry = (
            f"\n## {ts} [{session_id}] {', '.join(sorted(set(hits)))}\n"
            f"cwd: `{cwd}`\n\n"
            f"> {excerpt}\n"
        )

        INBOX.parent.mkdir(parents=True, exist_ok=True)
        if not INBOX.exists():
            INBOX.write_text(
                "# Surprises — User Corrections & Confirmations\n\n"
                "Auto-captured by surprise_catcher.py (UserPromptSubmit hook).\n"
                "Each entry: a user prompt matching correction/confirmation patterns.\n"
                "Reviewed via `/memory-review` — promote to memory or mark .rejected.\n"
                "\n---\n"
            )
        with INBOX.open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass  # fail-open
    return 0


if __name__ == "__main__":
    sys.exit(main())
