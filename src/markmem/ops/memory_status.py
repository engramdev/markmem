#!/usr/bin/env python3
"""
memory_status.py — one-screen health dashboard.

Reads existing JSON cache + metrics + sessions. NO new computation, just summary.
Called by /memory-status slash command. Sub-200ms typical.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from markmem import paths

MEMORY_DIR = paths.MEMORY_DIR
CACHE = paths.INDEX_CACHE
HEALTH = paths.HEALTH
INBOX = paths.INBOX
SESSIONS = MEMORY_DIR / "sessions"
QUIZ_LOG = paths.METRICS / "quiz_log.jsonl"
CONF_LOG = paths.CONFIDENCE_HISTORY


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def count_jsonl_recent(path: Path, days: int = 30) -> int:
    if not path.exists():
        return 0
    cutoff = datetime.now().timestamp() - days * 86400
    count = 0
    try:
        with path.open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                    ts = datetime.fromisoformat(e["ts"]).timestamp()
                    if ts >= cutoff:
                        count += 1
                except Exception:
                    pass
    except Exception:
        pass
    return count


def git_summary() -> str:
    if not (MEMORY_DIR / ".git").exists():
        return "(no git)"
    try:
        out = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=MEMORY_DIR, capture_output=True, text=True, timeout=2
        )
        lines = out.stdout.strip().split("\n")[:3]
        return f"{len(out.stdout.strip().split(chr(10)))} commits (last 3: {'; '.join(l.split(maxsplit=1)[1][:50] for l in lines)})"
    except Exception:
        return "(git error)"


def main() -> int:
    cache = load_json(CACHE)
    health = load_json(HEALTH)
    if not cache:
        print("No cache. Run: markmem-audit (markmem.ops.memory_audit) first.")
        return 1

    total = cache["totals"]["files"]
    total_tokens = cache["totals"]["est_tokens_total"]
    indexed_core = len(cache.get("indexed_in_core", []))
    indexed_deep = len(cache.get("indexed_in_deep", []))
    issues = health.get("issues", {})

    # Top tax
    memories = cache.get("memories", {})
    top_tax = sorted(
        ((m.get("est_tokens", 0), name) for name, m in memories.items() if "error" not in m),
        reverse=True,
    )[:5]

    # Confidence/importance distribution
    by_type: dict[str, list] = {}
    for name, m in memories.items():
        if "error" in m:
            continue
        t = m.get("type", "unknown")
        by_type.setdefault(t, []).append(m)

    # Sessions in last 7d
    recent_sessions = 0
    if SESSIONS.exists():
        cutoff = datetime.now().timestamp() - 7 * 86400
        for f in SESSIONS.glob("*.md"):
            if f.name == "README.md":
                continue
            if f.stat().st_mtime >= cutoff:
                recent_sessions += 1

    # Inbox state
    inbox_counts = {}
    for name in ("pending_memories.md", "surprises.md", "contradictions.md", "cron_alerts.md"):
        p = INBOX / name
        if p.exists():
            text = p.read_text(encoding="utf-8")
            inbox_counts[name] = len([l for l in text.split("\n") if l.startswith("## ")])

    # Trends (recent confidence updates)
    recent_outcomes = count_jsonl_recent(CONF_LOG, days=30)
    recent_quizzes = count_jsonl_recent(QUIZ_LOG, days=30)

    # ---- render ----
    print("=" * 70)
    print(f"  🧠 MEMORY STATUS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    print()
    print(f"  Files: {total} total · {indexed_core} in MEMORY.md · {indexed_deep} in MEMORY_DEEP.md")
    md_lines = health.get("summary", {}).get("MEMORY_md_lines", "?")
    print(f"  MEMORY.md: {md_lines}/195 lines (auto-loaded every session)")
    print()
    print(f"  Token-tax pool: {total_tokens:,} tokens total (loaded on-demand)")
    print("  Top-5 heaviest files:")
    for tokens, name in top_tax:
        bar = "█" * int(tokens / 400)
        print(f"    {tokens:>5} {bar:<10} {name}")
    print()
    print("  By type:")
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
    for t in sorted(by_type):
        files = by_type[t]
        confs = [safe_float(m.get("confidence")) for m in files]
        imps = [safe_int(m.get("importance")) for m in files]
        valid_c = [c for c in confs if c > 0]
        valid_i = [i for i in imps if i > 0]
        avg_conf = sum(valid_c) / len(valid_c) if valid_c else 0
        avg_imp = sum(valid_i) / len(valid_i) if valid_i else 0
        label = t if t else "(no type)"
        print(f"    {label:>10}: {len(files):>3} files · avg confidence={avg_conf:.2f} · avg importance={avg_imp:.1f}")
    print()
    print("  Health: ", end="")
    crit = sum(len(issues.get(k, [])) for k in ("frontmatter_invalid", "missing_index_targets", "duplicate_slugs", "index_oversize"))
    warn = sum(len(issues.get(k, [])) for k in ("oversize", "broken_wikilinks", "stale_unverified"))
    print(f"{'✓' if crit == 0 else '✗'} critical={crit} · ⚠ warnings={warn}")
    if issues.get("broken_wikilinks"):
        print(f"    └─ broken_wikilinks: {len(issues['broken_wikilinks'])} (consider /memory-stub)")
    if issues.get("oversize"):
        print(f"    └─ oversize files: {len(issues['oversize'])} (consider /memory-review for splits)")
    print()
    print("  Activity:")
    print(f"    Sessions captured (7d): {recent_sessions}")
    print(f"    Outcome backprops (30d): {recent_outcomes}")
    print(f"    Quizzes run (30d): {recent_quizzes}")
    print()
    print("  Inbox:")
    if inbox_counts:
        for name, n in inbox_counts.items():
            marker = "⚠" if n > 0 else "✓"
            print(f"    {marker} {name}: {n} items")
    else:
        print("    ✓ empty")
    print()
    print(f"  Git: {git_summary()}")
    print()
    if any(n > 0 for n in inbox_counts.values()) or issues.get("broken_wikilinks") or crit > 0:
        print("  → Run /memory-review to triage")
    else:
        print("  → System healthy. No action needed.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
