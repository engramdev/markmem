#!/usr/bin/env python3
"""
migrate_frontmatter_v2.py — add v2 frontmatter fields ADDITIVELY.

Adds these fields if missing (never overwrites existing values):
  importance     : default by type (HARD-GATE files get higher, others default)
  confidence     : 0.8 default (user-created memories assumed trustworthy)
  last_verified  : <today> (will age naturally, /memory-quiz flags stale)
  created        : file mtime as ISO date (best guess for old files)

Hard rules:
  - Default = DRY-RUN. --write to commit.
  - NEVER overwrite existing field values.
  - Only modify the YAML frontmatter block, not the body.
  - Backup created per-file before write (.bak.<ts>) only on --write.
  - Skip files without valid frontmatter (audit will flag those separately).
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

from markmem import paths

MEMORY_DIR = paths.MEMORY_DIR
INDEX_FILES = {paths.INDEX_FILE.name, paths.DEEP_FILE.name}
BACKUP_DIR = MEMORY_DIR / "_archive" / "frontmatter_v2_migration"

# Defaults per type
DEFAULT_IMPORTANCE = {"feedback": 5, "project": 6, "reference": 4, "user": 7}
DEFAULT_CONFIDENCE = 0.80
HARD_GATE_IMPORTANCE_BUMP = 2  # files referenced in HARD-GATES section get +2

FRONTMATTER_RE = re.compile(r"^(---\n)(.*?)(\n---\n)", re.DOTALL)


def read_hard_gate_files() -> set[str]:
    idx = paths.INDEX_FILE
    if not idx.exists():
        return set()
    text = idx.read_text(encoding="utf-8")
    in_hg = False
    out = set()
    for line in text.split("\n"):
        if line.startswith("## ⛔ HARD-GATES"):
            in_hg = True
            continue
        if in_hg:
            if line.startswith("## "):
                break
            m = re.search(r"\(([a-zA-Z0-9_\-]+\.md)\)", line)
            if m:
                out.add(m.group(1))
    return out


def has_field(fm_body: str, field: str) -> bool:
    return bool(re.search(rf"^\s*{re.escape(field)}:", fm_body, re.MULTILINE))


def get_type(fm_body: str) -> str:
    m = re.search(r"^\s*type:\s*(\S+)", fm_body, re.MULTILINE)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def ensure_metadata_block(fm_body: str) -> str:
    """If `metadata:` line missing, add empty one before --- end."""
    if re.search(r"^metadata:", fm_body, re.MULTILINE):
        return fm_body
    # Append at end (with proper newline handling)
    return fm_body.rstrip() + "\nmetadata:\n  type: \n"


def add_field_under_metadata(fm_body: str, field: str, value) -> str:
    """Add 'field: value' as nested under metadata. Preserves indentation."""
    # find metadata: line, insert after at indent 2
    lines = fm_body.split("\n")
    out = []
    inserted = False
    for i, line in enumerate(lines):
        out.append(line)
        if not inserted and re.match(r"^metadata:\s*$", line):
            # Insert after metadata: line, at end of metadata block
            # Find where metadata block ends (next non-indented line or eof)
            insert_at = len(out)
            j = i + 1
            while j < len(lines) and (lines[j].startswith("  ") or lines[j].strip() == ""):
                j += 1
            # Insert just before line j
            new_line = f"  {field}: {value}"
            # we keep building 'out' from lines linearly so we need different approach
            # Instead: build all lines fresh
            break
    # Simpler approach: rebuild lines
    new_lines = []
    i = 0
    inserted = False
    while i < len(lines):
        line = lines[i]
        new_lines.append(line)
        if not inserted and re.match(r"^metadata:\s*$", line):
            # collect block lines
            j = i + 1
            block_lines = []
            while j < len(lines) and (lines[j].startswith("  ") or (lines[j].strip() == "" and j + 1 < len(lines) and lines[j+1].startswith("  "))):
                block_lines.append(lines[j])
                j += 1
            for bl in block_lines:
                new_lines.append(bl)
            new_lines.append(f"  {field}: {value}")
            inserted = True
            i = j
            continue
        i += 1
    return "\n".join(new_lines)


def migrate_file(path: Path, today: str, hard_gates: set[str], dry_run: bool) -> dict:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {"file": path.name, "status": "skipped", "reason": "no frontmatter"}

    fm_open, fm_body, fm_close = m.group(1), m.group(2), m.group(3)
    body_after = text[m.end():]

    type_ = get_type(fm_body)
    is_hg = path.name in hard_gates
    base_imp = DEFAULT_IMPORTANCE.get(type_, 5)
    importance = min(10, base_imp + (HARD_GATE_IMPORTANCE_BUMP if is_hg else 0))

    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    except Exception:
        mtime = today

    fields_to_add = {
        "importance": importance,
        "confidence": DEFAULT_CONFIDENCE,
        "last_verified": today,
        "created": mtime,
    }

    new_fm = ensure_metadata_block(fm_body)
    added = []
    for field, value in fields_to_add.items():
        if not has_field(new_fm, field):
            new_fm = add_field_under_metadata(new_fm, field, value)
            added.append(field)

    if not added:
        return {"file": path.name, "status": "already-v2", "added": []}

    new_text = fm_open + new_fm + fm_close + body_after

    if dry_run:
        return {"file": path.name, "status": "would-add", "added": added, "is_hg": is_hg, "importance": importance}

    # Write with backup in dedicated dir (single tree, not 143 .bak.* in memory/)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    (BACKUP_DIR / path.name).write_text(text)
    path.write_text(new_text)
    return {"file": path.name, "status": "added", "added": added, "is_hg": is_hg, "importance": importance}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="apply changes (default = dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="process only first N (for staged rollout)")
    ap.add_argument("--filter", default="", help="only files matching this substring")
    args = ap.parse_args()

    today = date.today().isoformat()
    hard_gates = read_hard_gate_files()

    results = []
    count = 0
    for path in sorted(MEMORY_DIR.glob("*.md")):
        if path.name in INDEX_FILES:
            continue
        if args.filter and args.filter not in path.name:
            continue
        results.append(migrate_file(path, today, hard_gates, dry_run=not args.write))
        count += 1
        if args.limit and count >= args.limit:
            break

    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    print(f"Mode: {'WRITE' if args.write else 'DRY-RUN'}")
    print(f"Processed: {len(results)}")
    for status, n in sorted(by_status.items()):
        print(f"  {status}: {n}")
    print()

    if not args.write:
        print("Sample changes (first 10):")
        for r in results[:10]:
            if r["status"] in ("would-add", "added"):
                hg = " [HARD-GATE]" if r.get("is_hg") else ""
                print(f"  + {r['file']:60s}  imp={r['importance']}{hg}  add={','.join(r['added'])}")
        print(f"\n(dry-run — re-run with --write to apply. Per-file backups created on write.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
