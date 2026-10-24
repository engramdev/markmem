#!/usr/bin/env python3
"""
correction_synapse.py — the highest-leverage learning signal.

surprise_catcher.py captures what the user *says* ("no, wrong"). It cannot capture
what the user *silently edits* in a file after the assistant produced it. That silent
diff — "I wrote X, you committed Y" — is the most precise lesson there is. This synapse
captures it.

Mechanism (hash + bounded snapshot + difflib — works everywhere, in any tree, not just
git repos; `git log` is enrichment only):

  --capture <transcript>   (SessionEnd hook; reads the hook JSON on stdin)
      Parse the transcript for files the assistant wrote/edited this session. For each
      existing text file under the size cap, store a snapshot of the assistant's version
      + sha256 in a watch manifest. This is "the assistant's state at session end".

  --scan                   (SessionStart hook + cron)
      For each watched file: compare current content vs the snapshot.
        changed   → the user corrected it afterwards → emit a correction candidate
                    (unified diff, git-enriched) to inbox/corrections.md, then drop from
                    the watch + prune the snapshot.
        unchanged → keep watching until WATCH_DAYS, then drop (no correction = no lesson).
                    Bounds storage.

Hard rules:
  - Fail-open everywhere: any error → exit 0. Never block a session.
  - Snapshots/manifest are LOCAL only — never committed (they hold code/secrets). The
    repo .gitignore excludes inbox/.edit_snapshots/ + inbox/.edit_state.json.
  - Emits CANDIDATES only — never writes a memory. Promotion stays human-gated (a silent
    edit may be a real correction OR normal further work; only the user decides).
  - Pure stdlib, no network, no LLM, bounded CPU (2 MB transcript cap, 256 KB/file).
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from markmem import paths

MEMORY_DIR = paths.MEMORY_DIR
INBOX = paths.INBOX
SNAP_DIR = INBOX / ".edit_snapshots"
STATE = INBOX / ".edit_state.json"
CORRECTIONS = INBOX / "corrections.md"

MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
MAX_SNAP_BYTES = 256 * 1024          # don't snapshot huge files (data dumps etc.)
WATCH_DAYS = 14                      # unchanged after this → user never corrected → drop
MAX_DIFF_LINES = 80                  # cap a candidate's diff in the inbox

# Never watch our own plumbing / secrets / volatile dirs.
SKIP_SUBSTRINGS = (
    str(MEMORY_DIR.resolve()) + os.sep,  # don't watch the memory store itself
    "/.ssh/", "/secrets.env", ".secrets", "token.json", "api-keys",
    "credentials", ".env", "/tmp/",
)
TEXT_EXTS = {
    ".py", ".md", ".sh", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".txt", ".toml", ".cfg", ".conf", ".html", ".css", ".swift", ".go", ".rs",
    ".sql", ".env.example", ".tsv", ".csv", ".xml",
}


def _load_state() -> list[dict]:
    if not STATE.exists():
        return []
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_state(entries: list[dict]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(entries, indent=1), encoding="utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_watchable(path: str) -> bool:
    if not path or path == "?":
        return False
    if any(s in path for s in SKIP_SUBSTRINGS):
        return False
    p = Path(path)
    # text by extension, or extensionless small config
    if p.suffix.lower() not in TEXT_EXTS and p.suffix:
        return False
    return True


# --------------------------------------------------------------------------- #
# capture (SessionEnd)
# --------------------------------------------------------------------------- #
def _tail_read(path: Path, max_bytes: int) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            f.readline()
        return f.read().decode("utf-8", errors="replace")


def _edited_files_from_transcript(text: str) -> set[str]:
    files: set[str] = set()
    for raw in text.split("\n"):
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = e.get("message") or e
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "tool_use":
                continue
            name = part.get("name", "")
            inp = part.get("input", {}) or {}
            if name in ("Write", "Edit", "MultiEdit"):
                fp = inp.get("file_path")
                if fp:
                    files.add(fp)
            elif name == "NotebookEdit":
                fp = inp.get("notebook_path")
                if fp:
                    files.add(fp)
    return files


def capture(transcript_path: str, session_id: str) -> int:
    if not transcript_path or not os.path.exists(transcript_path):
        return 0
    text = _tail_read(Path(transcript_path), MAX_TRANSCRIPT_BYTES)
    if not text:
        return 0
    edited = {f for f in _edited_files_from_transcript(text) if _is_watchable(f)}
    if not edited:
        return 0

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    now = datetime.now().isoformat()
    added = 0

    for fp in edited:
        try:
            p = Path(fp)
            if not p.is_file() or p.stat().st_size > MAX_SNAP_BYTES:
                continue
            data = p.read_bytes()
            sha = _sha(data)
            snap_name = _sha(fp.encode())[:16] + ".snap"
            (SNAP_DIR / snap_name).write_bytes(data)
            # replace any existing watch for this path (latest assistant state wins)
            state = [e for e in state if e["path"] != fp]
            state.append({
                "path": fp, "snap": snap_name, "sha": sha,
                "captured": now, "session": session_id[:8],
            })
            added += 1
        except Exception:
            continue

    _save_state(state)
    return added


# --------------------------------------------------------------------------- #
# scan (SessionStart + cron)
# --------------------------------------------------------------------------- #
def _git_log(path: str) -> str | None:
    """If path is in a git repo, return the file's last commit line (enrichment)."""
    try:
        repo = subprocess.run(
            ["git", "-C", str(Path(path).parent), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if repo.returncode != 0:
            return None
        out = subprocess.run(
            ["git", "-C", str(Path(path).parent), "log", "-1", "--format=%h %an %s", "--", path],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _unified(old: str, new: str, path: str) -> list[str]:
    diff = list(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{Path(path).name} (assistant)", tofile=f"b/{Path(path).name} (user)",
        lineterm="", n=2,
    ))
    if len(diff) > MAX_DIFF_LINES:
        diff = diff[:MAX_DIFF_LINES] + [f"... (+{len(diff) - MAX_DIFF_LINES} more diff lines, truncated)"]
    return diff


def scan() -> int:
    state = _load_state()
    if not state:
        return 0
    keep: list[dict] = []
    candidates: list[dict] = []
    cutoff = datetime.now() - timedelta(days=WATCH_DAYS)

    for e in state:
        fp, snap_name = e["path"], e["snap"]
        snap_path = SNAP_DIR / snap_name
        p = Path(fp)
        try:
            if not p.is_file() or not snap_path.exists():
                snap_path.unlink(missing_ok=True)      # file or snap gone → stop watching
                continue
            cur = p.read_bytes()
            if _sha(cur) == e["sha"]:
                # unchanged: keep watching until WATCH_DAYS, then drop
                try:
                    captured = datetime.fromisoformat(e["captured"])
                except Exception:
                    captured = datetime.now()
                if captured < cutoff:
                    snap_path.unlink(missing_ok=True)
                else:
                    keep.append(e)
                continue
            # CHANGED → correction candidate
            old = snap_path.read_text(encoding="utf-8", errors="replace")
            new = cur.decode("utf-8", errors="replace")
            candidates.append({
                "path": fp,
                "captured": e["captured"],
                "session": e.get("session", "?"),
                "git": _git_log(fp),
                "diff": _unified(old, new, fp),
            })
            snap_path.unlink(missing_ok=True)            # resolved → prune
        except Exception:
            keep.append(e)                               # on error keep watching

    _save_state(keep)
    if candidates:
        _emit_candidates(candidates)
    return len(candidates)


def _emit_candidates(cands: list[dict]) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    CORRECTIONS.parent.mkdir(parents=True, exist_ok=True)
    if not CORRECTIONS.exists():
        header = (
            "# Corrections — silent code corrections (correction synapse)\n\n"
            "Auto-captured by correction_synapse.py: files you silently changed after the\n"
            "assistant's last edit. The diff is the most precise learning signal there is.\n"
            "**Candidates, not memories** — a human decides: a real correction (derive the\n"
            "lesson) vs. normal further work.\n\n---\n"
        )
        CORRECTIONS.write_text(header, encoding="utf-8")

    with CORRECTIONS.open("a", encoding="utf-8") as f:
        for c in cands:
            f.write(f"\n## {ts} — `{c['path']}`\n")
            f.write(f"Assistant state: {c['captured']} (session {c['session']})")
            if c["git"]:
                f.write(f" · git: {c['git']}")
            f.write("\n\nQuestion: was this an **assistant mistake** or **normal further work**?\n\n")
            f.write("```diff\n" + "\n".join(c["diff"]) + "\n```\n")


# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        g = ap.add_mutually_exclusive_group(required=True)
        g.add_argument("--capture", action="store_true",
                       help="SessionEnd: snapshot assistant-edited files (reads hook JSON on stdin)")
        g.add_argument("--scan", action="store_true",
                       help="SessionStart/cron: detect user changes → correction candidates")
        g.add_argument("--status", action="store_true", help="show watch state")
        args = ap.parse_args()

        if args.status:
            st = _load_state()
            print(f"Watched files: {len(st)}")
            for e in st:
                print(f"  {e['captured'][:16]}  {e['path']}")
            print(f"Corrections inbox: {CORRECTIONS} ({'exists' if CORRECTIONS.exists() else 'none'})")
            return 0

        if args.capture:
            raw = sys.stdin.read()
            try:
                data = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                data = {}
            capture(data.get("transcript_path", ""), data.get("session_id", "unknown"))
            return 0

        if args.scan:
            scan()
            return 0
    except Exception:
        pass  # fail-open
    return 0


if __name__ == "__main__":
    sys.exit(main())
