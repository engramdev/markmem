#!/usr/bin/env python3
"""
memory_index_rebuild.py — preserve-curation index sync for MEMORY.md.

Goals:
  - Validate every entry in MEMORY.md points to a real file
  - Append any orphan (file exists but not indexed) to "🆕 Unsorted" section
  - Comment out (don't delete) entries whose files vanished — preserves user curation
  - Default = DRY-RUN. Show diff. Only --write commits.

Hard guarantee:
  - Never deletes user prose, never reorders sections, never alters bullet wording.
  - Only operations: append-to-Unsorted, comment-out-missing, no-op for valid entries.

This is intentionally minimal. The user curates section taxonomy and stars manually;
the script just stops drift between MEMORY.md and the filesystem.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from markmem import paths

MEMORY_DIR = paths.MEMORY_DIR
INDEX_FILE = paths.INDEX_FILE
DEEP_INDEX = paths.DEEP_FILE
INFRA_INDEX = paths.INFRA_FILE
INDEX_FILES = {INDEX_FILE.name, DEEP_INDEX.name, INFRA_INDEX.name}
UNSORTED_HEADER = "## 🆕 Unsorted — needs categorization"

LINK_RE = re.compile(r"\[([a-zA-Z0-9_\-]+\.md)\]\(([a-zA-Z0-9_\-]+\.md)\)")
HEADER_RE = re.compile(r"^(#{2,3})\s+")


def existing_files() -> set[str]:
    return {p.name for p in MEMORY_DIR.glob("*.md") if p.name not in INDEX_FILES}


def indexed_files(text: str) -> set[str]:
    """Files linked from a given index text."""
    return {m.group(2) for m in LINK_RE.finditer(text) if m.group(2) not in INDEX_FILES}


def all_indexed_files() -> set[str]:
    """Files linked from ANY tier (core + deep)."""
    out: set[str] = set()
    for idx in (INDEX_FILE, DEEP_INDEX, INFRA_INDEX):
        if idx.exists():
            out |= indexed_files(idx.read_text(encoding="utf-8"))
    return out


def rebuild(text: str, files_on_disk: set[str], all_indexed: set[str]) -> tuple[str, dict]:
    """Return (new_text, change_report).

    `all_indexed` includes files referenced by ANY tier so we don't flag deep-tier entries as orphans.
    """
    in_this_tier = indexed_files(text)
    missing = in_this_tier - files_on_disk    # in THIS index but file gone
    orphans = files_on_disk - all_indexed     # file on disk but not in any tier

    lines = text.split("\n")
    new_lines: list[str] = []

    for line in lines:
        m = LINK_RE.search(line)
        if m and m.group(2) in missing and not line.lstrip().startswith("<!--"):
            new_lines.append(f"<!-- MISSING: {line.strip()} -->")
        else:
            new_lines.append(line)

    # Append orphans
    if orphans:
        if UNSORTED_HEADER not in text:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append(UNSORTED_HEADER)
            new_lines.append("")
            new_lines.append(
                f"_Auto-appended by memory_index_rebuild on {datetime.now().strftime('%Y-%m-%d')}. "
                "Move each line into the correct semantic section above, then delete this header._"
            )
            new_lines.append("")

        for fname in sorted(orphans):
            desc = _extract_description(MEMORY_DIR / fname)
            new_lines.append(f"- [{fname}]({fname}) — {desc}")

    return "\n".join(new_lines), {
        "missing_count": len(missing),
        "missing": sorted(missing),
        "orphan_count": len(orphans),
        "orphans": sorted(orphans),
    }


def _extract_description(path: Path) -> str:
    """Pull `description:` from frontmatter; fall back to placeholder."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return "(unreadable — please review)"
    m = re.search(r"^description:\s*(.+?)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return "(no description — add to frontmatter and re-run)"


def diff_summary(old: str, new: str) -> str:
    old_lines = old.split("\n")
    new_lines = new.split("\n")
    added = [l for l in new_lines if l not in old_lines]
    removed = [l for l in old_lines if l not in new_lines]
    out = []
    if removed:
        out.append("--- REMOVED / TRANSFORMED ---")
        for l in removed[:20]:
            out.append(f"  - {l}")
        if len(removed) > 20:
            out.append(f"  ... +{len(removed) - 20} more")
    if added:
        out.append("--- ADDED ---")
        for l in added[:20]:
            out.append(f"  + {l}")
        if len(added) > 20:
            out.append(f"  ... +{len(added) - 20} more")
    if not added and not removed:
        out.append("(no changes)")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="apply changes (default = dry-run)")
    args = ap.parse_args(argv)

    text = INDEX_FILE.read_text(encoding="utf-8")
    files = existing_files()
    all_idx = all_indexed_files()
    new_text, report = rebuild(text, files, all_idx)

    print("=" * 64)
    print("MEMORY.md INDEX REBUILD")
    print("=" * 64)
    print(f"Mode: {'WRITE' if args.write else 'DRY-RUN'}")
    print(f"Indexed entries (core): {len(indexed_files(text))}")
    print(f"Indexed entries (all tiers): {len(all_idx)}")
    print(f"Files on disk: {len(files)}")
    print(f"Missing (in index, no file): {report['missing_count']}")
    for x in report["missing"]:
        print(f"   - {x}")
    print(f"Orphans (file, not in index): {report['orphan_count']}")
    for x in report["orphans"]:
        print(f"   + {x}")
    print()
    print(diff_summary(text, new_text))
    print()
    old_lines = len(text.split("\n"))
    new_lines = len(new_text.split("\n"))
    print(f"MEMORY.md: {old_lines} → {new_lines} lines (limit 195, truncation at 200)")

    if new_text == text:
        print("\n✓ Index is in sync with filesystem. No changes needed.")
        return 0

    if args.write:
        backup = INDEX_FILE.with_suffix(f".md.bak.{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        backup.write_text(text)
        INDEX_FILE.write_text(new_text)
        print(f"\n✓ Wrote MEMORY.md. Backup: {backup.name}")
    else:
        print("\n(dry-run — re-run with --write to apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
