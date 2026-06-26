#!/usr/bin/env python3
"""
find_related_memories.py — A-MEM-style auto-linker (Zettelkasten).

Given a target memory file, find top-K most related memories by token overlap
of significant terms. No ML, no embeddings — fast and explainable.

Use cases:
  - Called by /memory-review when a new memory is promoted (suggest [[links]])
  - Called by /memory-link standalone to refresh a single memory's links
  - Called batched to find weakly-connected memories that should link to peers

Algorithm:
  1. Tokenize each memory: alphanumeric, length ≥ 4, lowercased, stop-word filtered.
  2. For each pair, compute Jaccard overlap on token sets, weighted by IDF.
  3. Rank candidates against the target; return top-K with a similarity score.
  4. Exclude pairs already cross-linked.

Output: JSON list of {file, score, shared_terms[:8], already_linked}.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter

from markmem.config import MEMORY_DIR

STOPWORDS = {
    # English
    "this", "that", "with", "from", "have", "been", "will", "would", "could",
    "should", "their", "there", "which", "where", "when", "then", "than",
    "what", "your", "more", "into", "some", "only", "such", "also", "very",
    "just", "even", "much", "many", "most", "they", "them", "these", "those",
    "about", "after", "before", "first", "other", "same", "still", "well",
    "make", "made", "take", "taken", "give", "given", "find", "found",
    # German
    "wenn", "dann", "aber", "auch", "nicht", "noch", "schon", "doch", "denn",
    "vor", "nach", "über", "unter", "mit", "ohne", "bei", "ohne", "wie",
    "weil", "damit", "dass", "ein", "eine", "einer", "eines", "der", "die",
    "das", "den", "dem", "des", "und", "oder", "aber", "sein", "haben",
    "werden", "können", "müssen", "sollen", "wollen", "diese", "dieser",
    "dieses", "alle", "alles", "nichts", "etwas", "immer", "nie", "noch",
    # Markdown / structural
    "https", "http", "file", "line", "code", "text", "list", "item",
    "memory", "memories", "feedback", "project", "reference", "user",
    "name", "description", "metadata", "type",
}

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{3,}")
WIKILINK_RE = re.compile(r"\[\[([a-zA-Z0-9_\-]+)\]\]")
NAMEFIELD_RE = re.compile(r"^name:\s*(\S+)", re.MULTILINE)


def tokenize(text: str) -> Counter[str]:
    return Counter(
        t.lower() for t in TOKEN_RE.findall(text)
        if t.lower() not in STOPWORDS
    )


def build_corpus() -> tuple[dict[str, Counter[str]], dict[str, set[str]], dict[str, str]]:
    """Return (token_counts, wiki_link_targets, slug_to_filename)."""
    tokens: dict[str, Counter[str]] = {}
    links: dict[str, set[str]] = {}
    slug_to_file: dict[str, str] = {}
    for path in MEMORY_DIR.glob("*.md"):
        if path.name == "MEMORY.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        tokens[path.name] = tokenize(text)
        links[path.name] = set(WIKILINK_RE.findall(text))
        m = NAMEFIELD_RE.search(text)
        if m:
            slug_to_file[m.group(1)] = path.name
    return tokens, links, slug_to_file


def compute_idf(corpus: dict[str, Counter[str]]) -> dict[str, float]:
    n_docs = len(corpus)
    df: Counter[str] = Counter()
    for counts in corpus.values():
        for term in counts:
            df[term] += 1
    return {term: math.log(n_docs / (1 + d)) for term, d in df.items()}


def weighted_jaccard(a: Counter[str], b: Counter[str], idf: dict[str, float]) -> tuple[float, list[str]]:
    common = set(a) & set(b)
    if not common:
        return 0.0, []
    weighted_inter = sum(idf.get(t, 0.0) * min(a[t], b[t]) for t in common)
    weighted_union = sum(
        idf.get(t, 0.0) * max(a.get(t, 0), b.get(t, 0))
        for t in (set(a) | set(b))
    )
    score = weighted_inter / weighted_union if weighted_union > 0 else 0.0
    top_terms = sorted(common, key=lambda t: idf.get(t, 0) * min(a[t], b[t]), reverse=True)[:8]
    return score, top_terms


def find_for_text(text: str, k: int, min_score: float) -> list[dict]:
    """Dedup-Helfer für den Promote-Flow: Top-K existierende Memories, die einem
    NOCH-NICHT-geschriebenen Entwurfs-Body am ähnlichsten sind. Fängt 'gleiche
    Lehre, andere Worte' — besser als grep auf Wortgleichheit.

    Metrik = IDF-gewichtete COVERAGE (Containment): wie viel des Entwurfs ist im
    Kandidaten gedeckt — NICHT symmetrisches Jaccard (das bestraft kurzen Entwurf
    gegen langes File, weil die Union vom File dominiert wird)."""
    tokens, _, _ = build_corpus()
    idf = compute_idf(tokens)
    draft = tokenize(text)
    draft_weight = sum(idf.get(t, 0.0) * c for t, c in draft.items())
    if draft_weight <= 0:
        return []
    out = []
    for fname, counts in tokens.items():
        common = set(draft) & set(counts)
        if not common:
            continue
        inter = sum(idf.get(t, 0.0) * min(draft[t], counts[t]) for t in common)
        coverage = inter / draft_weight
        if coverage >= min_score:
            shared = sorted(common, key=lambda t: idf.get(t, 0) * min(draft[t], counts[t]), reverse=True)[:8]
            out.append({"file": fname, "score": round(coverage, 4), "shared_terms": shared})
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:k]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", nargs="?", help="filename or slug of memory to find relatives for (omit if --text)")
    ap.add_argument("--text", action="store_true", help="dedup-mode: read a draft body from stdin, find similar existing memories")
    ap.add_argument("--k", type=int, default=8, help="top-K related to return")
    ap.add_argument("--min-score", type=float, default=0.02, help="min Jaccard score")
    ap.add_argument("--json", action="store_true", help="JSON output (default = human)")
    args = ap.parse_args()

    # Dedup-Modus: Entwurfs-Text von stdin gegen Korpus
    if args.text:
        draft = sys.stdin.read()
        if not draft.strip():
            print("[error] --text: kein Text auf stdin", file=sys.stderr)
            return 1
        # Coverage-Schwelle: ~0.30 = ein Drittel des Entwurfs-Signals ist schon gedeckt
        ms = args.min_score if args.min_score != 0.02 else 0.30
        results = find_for_text(draft, args.k, ms)
        if args.json:
            print(json.dumps({"mode": "text-dedup", "candidates": results}, indent=2, ensure_ascii=False))
        else:
            if not results:
                print(f"Keine ähnliche Memory ≥ {ms} — neu anlegen ok.")
            else:
                print(f"⚠ {len(results)} ähnliche Memory(s) ≥ {ms} — prüfen ob aktualisieren statt neu:")
                for c in results:
                    print(f"  {c['score']:.3f}  {c['file']}  (shared: {', '.join(c['shared_terms'][:5])})")
        return 0

    if not args.target:
        ap.error("target erforderlich (oder --text für Dedup-Modus)")

    tokens, links, slug_to_file = build_corpus()

    target = args.target
    if not target.endswith(".md"):
        # treat as slug
        target = slug_to_file.get(target) or f"{target}.md"
    if target not in tokens:
        print(f"[error] target not found: {target}", file=sys.stderr)
        return 1

    idf = compute_idf(tokens)
    target_tokens = tokens[target]
    target_links = links.get(target, set())

    # Existing links: resolve slugs to filenames for "already_linked" detection
    linked_files = set()
    for slug in target_links:
        if slug in slug_to_file:
            linked_files.add(slug_to_file[slug])

    candidates = []
    for fname, counts in tokens.items():
        if fname == target:
            continue
        score, shared = weighted_jaccard(target_tokens, counts, idf)
        if score < args.min_score:
            continue
        # Reverse-link check: does THIS file link to target?
        target_slug = None
        for s, f in slug_to_file.items():
            if f == target:
                target_slug = s
                break
        reverse_links_to_target = target_slug in links.get(fname, set()) if target_slug else False
        candidates.append({
            "file": fname,
            "score": round(score, 4),
            "shared_terms": shared,
            "already_linked_from_target": fname in linked_files,
            "already_links_back": reverse_links_to_target,
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    candidates = candidates[: args.k]

    if args.json:
        print(json.dumps({"target": target, "candidates": candidates}, indent=2))
        return 0

    print(f"Target: {target}")
    print(f"Existing wiki-links: {len(target_links)} ({sum(1 for l in target_links if l in slug_to_file)} resolved)")
    print()
    print(f"Top {len(candidates)} related (score ≥ {args.min_score}):")
    print()
    print(f"{'score':>6}  {'links?':<8}  file")
    print(f"{'-----':>6}  {'------':<8}  {'-' * 40}")
    for c in candidates:
        mark = []
        if c["already_linked_from_target"]:
            mark.append("from→")
        if c["already_links_back"]:
            mark.append("←to")
        mark_str = "+".join(mark) or "-"
        print(f"  {c['score']:.3f}  {mark_str:<8}  {c['file']}")
        print(f"          shared: {', '.join(c['shared_terms'][:6])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
