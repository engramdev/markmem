#!/usr/bin/env python3
"""
memory_audit.py — read-only health check for the file-based memory system.

Scans the memory directory for:
  - Frontmatter validity (name, description, type)
  - Oversize files (per type)
  - Orphans (file exists but NOT linked in MEMORY.md)
  - Missing index targets (MEMORY.md links a file that doesn't exist)
  - Broken [[wiki-links]] (slug points to non-existent memory)
  - Duplicate `name:` slugs across files
  - MEMORY.md size vs hard limit
  - Stale memories (last_verified > 90 days, if field present)

Outputs:
  - Human-readable report to stdout
  - JSON snapshot to metrics/memory_health.json
  - Exit 0 if clean, 1 if issues found (for CI / hook gating)

NEVER MODIFIES FILES. Safe to run on any cadence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from markmem import paths

MEMORY_DIR = paths.MEMORY_DIR
INDEX_FILE = paths.INDEX_FILE
# Additional index tiers (deep tier — loaded on-demand only, but entries still count as indexed)
INDEX_TIERS = [INDEX_FILE, paths.DEEP_FILE, paths.INFRA_FILE]
# Files that are indexes themselves, not memories
INDEX_FILES = {p.name for p in INDEX_TIERS}
METRICS_FILE = paths.HEALTH
# JSON cache consumed by other scripts (quiz, link, banner) to avoid re-parsing 130 files
INDEX_CACHE_FILE = paths.INDEX_CACHE
INDEX_CACHE_VERSION = 1

# Hard limits from feedback_memory_hygiene_rules.md
LIMITS = {
    "MEMORY.md": 195,
    "feedback": 60,
    "project": 150,
    "reference": 100,
    "user": 80,
}

# Files allowed to exceed limit (curated MASTER files)
SIZE_EXEMPT = {
    "feedback_2026-05-21_closure_wave_lessons.md",
    "feedback_senior_elite_target_recon_playbook.md",
    "reference_mcp_arsenal_2026-05-24.md",
    "project_target_review_2026-05-24.md",
    "project_workflows_overview.md",
    # Dichte Playbooks (Command-Rezepte + Referenz-Tabellen, kein Fett) — 2026-06-06
    # geprüft: Inhalt ist durchgehend Signal, Kürzen würde Wert vernichten.
    "feedback_aws_apigateway_waf_bypass.md",
    "feedback_bugbounty_scope_check.md",
    "feedback_caido_mcp_when_caido_runs.md",
    "feedback_cloudflare_tunnel_api_setup.md",
    "feedback_confidence_inflation_anti_pattern.md",
    "feedback_cra_env_leak_pattern.md",
    "feedback_dns_rfc1918_in_public.md",
    "feedback_program_status_check.md",
    "feedback_recon_before_submit.md",
    "feedback_rivian_documents_api_s3_multiregion.md",
}

# Directories under memory/ that are NOT individual memories
SKIP_DIRS = {"_archive", "_superseded", "inbox", "sessions", "metrics", "detail", "_audit"}

# Placeholder slugs used as documentation examples — never broken
PLACEHOLDER_SLUGS = {
    "other", "name", "other-memory-slug", "this-memory", "memory-name-slug",
    "your-name", "example", "foo", "bar", "related-1", "related-2",
    "link", "other-slug", "slug", "file",
}

# Memory type prefixes used to try resolving prefix-stripped links
TYPE_PREFIXES = ("feedback", "project", "reference", "user")

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([a-zA-Z0-9_\-]+)\]\]")
INDEX_LINK_RE = re.compile(r"\(([a-z0-9_.\-]+\.md)\)", re.IGNORECASE)  # Punkt erlaubt (z.B. *.sample.md)


def parse_frontmatter(text: str) -> dict | None:
    """Tolerant YAML-subset parser for our simple frontmatter."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    body = m.group(1)
    fm: dict = {}
    current_key = None
    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("  ") and current_key == "metadata":
            k, _, v = line.strip().partition(":")
            fm.setdefault("metadata", {})[k.strip()] = v.strip().strip('"').strip("'")
        elif ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            v = v.strip().strip('"').strip("'")
            if k.strip() == "metadata":
                current_key = "metadata"
                fm["metadata"] = {}
            else:
                current_key = k.strip()
                fm[k.strip()] = v
    return fm


def filename_to_normslug(fname: str) -> str:
    """Normalize a filename to comparable-with-wikilink form: drop .md, all _ -> -."""
    return fname[:-3].replace("_", "-") if fname.endswith(".md") else fname.replace("_", "-")


def normslug_match(link: str, filenames: set[str]) -> str | None:
    """Find a filename whose normalized form equals the wiki-link slug.

    Normalizes both sides to all-hyphens so [[user_foo]] and user_foo.md and user-foo.md all match.
    """
    link_norm = link.replace("_", "-")
    for fname in filenames:
        if filename_to_normslug(fname) == link_norm:
            return fname
    return None


def days_since(iso_date: str) -> int | None:
    try:
        d = datetime.strptime(iso_date.strip(), "%Y-%m-%d").date()
        return (date.today() - d).days
    except (ValueError, AttributeError):
        return None


def scan_memories() -> dict:
    """Walk memory/ and gather per-file metadata."""
    memories: dict[str, dict] = {}
    for path in sorted(MEMORY_DIR.glob("*.md")):
        if path.name in INDEX_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            memories[path.name] = {"error": f"read failed: {e}"}
            continue
        fm = parse_frontmatter(text) or {}
        meta = fm.get("metadata", {}) if isinstance(fm.get("metadata"), dict) else {}
        memories[path.name] = {
            "path": path,
            "lines": len(text.splitlines()),
            "chars": len(text),
            "est_tokens": len(text) // 4,
            "mtime": path.stat().st_mtime,
            "name": fm.get("name", ""),
            "description": fm.get("description", ""),
            "type": meta.get("type", ""),
            "importance": meta.get("importance", ""),
            "confidence": meta.get("confidence", ""),
            "last_verified": meta.get("last_verified", ""),
            "created": meta.get("created", ""),
            "wikilinks": set(WIKILINK_RE.findall(text)),
            "frontmatter_ok": bool(fm.get("name") and fm.get("description")),
        }
    return memories


def write_index_cache(memories: dict, indexed_core: set[str], indexed_deep: set[str]) -> None:
    """Write JSON cache other scripts read instead of re-parsing 130 files.

    Schema versioned via INDEX_CACHE_VERSION. Consumers check version before trusting.
    """
    payload = {
        "version": INDEX_CACHE_VERSION,
        "ts": datetime.now().isoformat(),
        "memory_dir": str(MEMORY_DIR),
        "memories": {},
        "indexed_in_core": sorted(indexed_core),
        "indexed_in_deep": sorted(indexed_deep),
        "totals": {
            "files": len(memories),
            "est_tokens_total": sum(m.get("est_tokens", 0) for m in memories.values() if "est_tokens" in m),
        },
    }
    for fname, info in memories.items():
        if "error" in info:
            payload["memories"][fname] = {"error": info["error"]}
            continue
        payload["memories"][fname] = {
            "name": info["name"],
            "description": info["description"],
            "type": info["type"],
            "importance": info["importance"],
            "confidence": info["confidence"],
            "last_verified": info["last_verified"],
            "created": info["created"],
            "lines": info["lines"],
            "chars": info["chars"],
            "est_tokens": info["est_tokens"],
            "mtime": info["mtime"],
            "wikilinks": sorted(info["wikilinks"]),
        }
    INDEX_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_CACHE_FILE.write_text(json.dumps(payload, indent=2, default=str))


def scan_index() -> tuple[set[str], int, dict[Path, set[str]]]:
    """Scan all index tiers. Return (combined linked, core-md-lines, per-tier sets)."""
    linked: set[str] = set()
    core_lines = 0
    per_tier: dict[Path, set[str]] = {}
    for idx_path in INDEX_TIERS:
        if not idx_path.exists():
            per_tier[idx_path] = set()
            continue
        text = idx_path.read_text(encoding="utf-8")
        this_tier: set[str] = set()
        for m in INDEX_LINK_RE.finditer(text):
            target = m.group(1)
            if target.endswith(".md") and target not in INDEX_FILES:
                this_tier.add(target)
        per_tier[idx_path] = this_tier
        linked |= this_tier
        if idx_path == INDEX_FILE:
            core_lines = len(text.splitlines())
    return linked, core_lines, per_tier


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-only", action="store_true", help="suppress human report")
    ap.add_argument("--strict", action="store_true", help="exit nonzero on any warning")
    ap.add_argument(
        "--write-inbox",
        action="store_true",
        help="write actionable issues (broken links, oversize) to inbox/contradictions.md",
    )
    args = ap.parse_args(argv)

    memories = scan_memories()
    indexed, index_lines, per_tier = scan_index()
    issues: dict[str, list] = {
        "frontmatter_invalid": [],
        "oversize": [],
        "orphans": [],
        "missing_index_targets": [],
        "broken_wikilinks": [],
        "duplicate_slugs": [],
        "stale_unverified": [],
        "index_oversize": [],
    }

    # 1. Frontmatter
    for fname, info in memories.items():
        if "error" in info:
            issues["frontmatter_invalid"].append(f"{fname}: {info['error']}")
            continue
        if not info["frontmatter_ok"]:
            issues["frontmatter_invalid"].append(
                f"{fname}: missing name/description"
            )

    # 2. Oversize
    for fname, info in memories.items():
        if "error" in info or fname in SIZE_EXEMPT:
            continue
        type_ = info["type"]
        limit = LIMITS.get(type_)
        if limit and info["lines"] > limit:
            issues["oversize"].append(f"{fname}: {info['lines']} > {limit} ({type_})")

    # 3. MEMORY.md size
    if index_lines > LIMITS["MEMORY.md"]:
        issues["index_oversize"].append(
            f"MEMORY.md: {index_lines} > {LIMITS['MEMORY.md']} (truncation at 200)"
        )

    # 4. Orphans (file exists but not in MEMORY.md)
    for fname in memories:
        if fname not in indexed:
            issues["orphans"].append(fname)

    # 5. Missing index targets (MEMORY.md links a file that doesn't exist)
    for target in indexed:
        if target not in memories:
            issues["missing_index_targets"].append(target)

    # 6. Broken wiki-links
    name_to_file = {info["name"]: fname for fname, info in memories.items() if info.get("name")}
    all_files = set(memories.keys())

    def resolve(link: str) -> str | None:
        """Return target filename or None if unresolvable."""
        if link in PLACEHOLDER_SLUGS:
            return "<placeholder>"
        if link in name_to_file:
            return name_to_file[link]
        hit = normslug_match(link, all_files)
        if hit:
            return hit
        # Try prefixing with each known type (handles [[-foo]] / bare [[foo]] typos)
        bare = link.lstrip("-")
        for pfx in TYPE_PREFIXES:
            candidate_slug = f"{pfx}-{bare}"
            if candidate_slug in name_to_file:
                return name_to_file[candidate_slug]
            hit = normslug_match(candidate_slug, all_files)
            if hit:
                return hit
        return None

    for fname, info in memories.items():
        if "error" in info:
            continue
        for link in info["wikilinks"]:
            if resolve(link) is None:
                issues["broken_wikilinks"].append(f"{fname} -> [[{link}]]")

    # 7. Duplicate slugs
    slug_owners: dict[str, list[str]] = {}
    for fname, info in memories.items():
        if info.get("name"):
            slug_owners.setdefault(info["name"], []).append(fname)
    for slug, owners in slug_owners.items():
        if len(owners) > 1:
            issues["duplicate_slugs"].append(f"{slug}: {', '.join(owners)}")

    # 8. Stale verification (only flag files that HAVE a last_verified field)
    for fname, info in memories.items():
        lv = info.get("last_verified")
        if lv:
            d = days_since(lv)
            if d is not None and d > 90:
                issues["stale_unverified"].append(f"{fname}: last_verified {d} days ago")

    # ---- Report ----
    summary = {
        "total_memories": len(memories),
        "indexed_in_MEMORY_md": len(indexed),
        "MEMORY_md_lines": index_lines,
        "MEMORY_md_limit": LIMITS["MEMORY.md"],
        "issue_counts": {k: len(v) for k, v in issues.items()},
        "ts": datetime.now().isoformat(),
    }

    if not args.json_only:
        print("=" * 64)
        print("MEMORY HEALTH AUDIT")
        print("=" * 64)
        print(f"Total memory files: {summary['total_memories']}")
        print(f"Indexed in MEMORY.md: {summary['indexed_in_MEMORY_md']}")
        print(
            f"MEMORY.md size: {index_lines}/{LIMITS['MEMORY.md']} lines"
            + ("  ⚠️ OVER LIMIT" if index_lines > LIMITS["MEMORY.md"] else "")
        )
        print()
        for k, v in issues.items():
            symbol = "✓" if not v else "✗"
            print(f"{symbol} {k}: {len(v)}")
            for item in v[:10]:
                print(f"    - {item}")
            if len(v) > 10:
                print(f"    ... and {len(v) - 10} more")
        print()

    # Snapshot health JSON
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(
        json.dumps({"summary": summary, "issues": issues}, indent=2, default=str)
    )

    # JSON index cache (consumed by quiz, link, banner — avoids re-parsing 130 files)
    indexed_core = per_tier.get(INDEX_FILE, set())
    indexed_deep_set = set()
    for p, files in per_tier.items():
        if p != INDEX_FILE:
            indexed_deep_set |= files
    write_index_cache(memories, indexed_core, indexed_deep_set)

    # Token-cost top-10 (SE.4 — surfaces big-win consolidation candidates)
    if not args.json_only:
        token_costs = sorted(
            ((info.get("est_tokens", 0), fname) for fname, info in memories.items() if "error" not in info),
            reverse=True,
        )[:10]
        print("Top-10 token tax (load-cost when read):")
        total_tokens = sum(info.get("est_tokens", 0) for info in memories.values() if "error" not in info)
        for tokens, fname in token_costs:
            pct = (tokens / total_tokens * 100) if total_tokens else 0
            print(f"  {tokens:>5} tokens  ({pct:4.1f}%)  {fname}")
        print(f"  ----- total across {len([m for m in memories.values() if 'error' not in m])} files: {total_tokens} tokens -----")
        print()

    if args.write_inbox:
        inbox_path = paths.INBOX / "contradictions.md"
        actionable = []
        if issues["broken_wikilinks"]:
            actionable.append("## Broken wiki-links\n")
            actionable.append("Each line: source-file -> [[unresolved-slug]]. Either fix the link or create the target.\n\n")
            for x in issues["broken_wikilinks"]:
                actionable.append(f"- {x}\n")
            actionable.append("\n")
        if issues["oversize"]:
            actionable.append("## Oversize candidates for split\n")
            actionable.append("Files exceeding the hygiene line-limit. Consider splitting or adding to SIZE_EXEMPT.\n\n")
            for x in issues["oversize"]:
                actionable.append(f"- {x}\n")
            actionable.append("\n")
        if issues["stale_unverified"]:
            actionable.append("## Stale memories (last_verified > 90d)\n\n")
            for x in issues["stale_unverified"]:
                actionable.append(f"- {x}\n")
            actionable.append("\n")
        if actionable:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            header = f"# Memory audit — {ts}\n\nFrom `memory_audit.py --write-inbox`. Review and fix; this file is overwritten on each run.\n\n"
            inbox_path.parent.mkdir(parents=True, exist_ok=True)
            inbox_path.write_text(header + "".join(actionable))
            print(f"[inbox] wrote {inbox_path}")
        elif inbox_path.exists():
            inbox_path.unlink()
            print(f"[inbox] no issues, removed {inbox_path}")

    if args.json_only:
        print(json.dumps(summary, indent=2))

    any_critical = any(
        issues[k] for k in ("frontmatter_invalid", "missing_index_targets", "duplicate_slugs", "index_oversize")
    )
    any_warning = any(issues.values())
    if any_critical:
        return 1
    if args.strict and any_warning:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
