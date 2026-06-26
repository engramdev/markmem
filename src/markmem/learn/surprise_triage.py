#!/usr/bin/env python3
"""
surprise_triage.py — the triage funnel for inbox/surprises.md.

Problem it solves: surprise_catcher.py is a keyword matcher → ~70% of captured
"surprises" are noise (build errors, "was jetzt", pure positive-confirmation).
/memory-review forces a human decision on EVERY item → nobody starts → backlog
grows monotonically (write-only liability, never read into context).

The funnel splits the triage into two halves with different risk profiles:

  Stage 1 — classify each surprise (deterministic, explainable):
      noise      → build/compiler errors, direction-seeking, terminal pastes,
                   pure confirmations. NON-behavioral + reversible → safe to
                   auto-archive to inbox/.rejected/ with a reason.
      dup        → semantically covered by an existing memory (term-overlap vs
                   the memory corpus, reusing the A-MEM tokenizer/IDF). Also
                   reversible → safe to auto-archive.
      candidate  → genuine signal (correction/omission/anti-pattern/rule). KEPT.
                   Behavior-changing → stays human-gated.

  Stage 1b — recurring-friction elevation (ExpeL / Fehler-Synapse, threshold 3):
      a noise signature seen >= 3 times is NOT noise — it is repeated pain.
      Elevated to candidate "recurring-friction" so the lesson is not lost.

  Stage 2 — cluster the candidates by theme (greedy weighted-Jaccard) and write
      a single digest (inbox/triage_digest.md) so the human approves ~5 patterns
      instead of triaging N raw lines.

Hard rules:
  - Default is DRY-RUN. Nothing moves without --apply.
  - --apply NEVER deletes: noise/dup blocks are MOVED (append) to
    inbox/.rejected/surprises_triaged_<ts>.md and removed from surprises.md.
  - Candidates are never auto-promoted to memory — that stays in /memory-review.
  - Pure stdlib, no network, no LLM. Fast and explainable.

Usage:
  surprise_triage.py                  # dry-run table + summary (default)
  surprise_triage.py --json           # dry-run as JSON
  surprise_triage.py --apply          # archive noise+dup, keep+cluster candidates
  surprise_triage.py --digest-only    # rebuild triage_digest.md from current candidates
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

from markmem import paths

MEMORY_DIR = paths.MEMORY_DIR
INBOX = paths.INBOX
SURPRISES = INBOX / "surprises.md"
REJECTED_DIR = INBOX / ".rejected"
DIGEST = INBOX / "triage_digest.md"

RECURRING_THRESHOLD = 3   # noise signature seen >= N times → elevated to candidate
DUP_SCORE = 0.12          # term-overlap vs a memory above this → treat as covered
CLUSTER_SCORE = 0.10      # candidate-to-candidate overlap above this → same cluster

# --- noise content signatures (checked against the excerpt, case-insensitive) ---
# These fired as "correction" by keyword but carry no behavioral lesson for Claude.
NOISE_BUILD = re.compile(
    r"(multiple commands produce|build input files cannot be found"
    r"|has no member|cannot be found|no such module|use of unresolved"
    r"|\.swift:\d+:\d+|\.py\", line \d+|compileswift|linker command failed"
    r"|undefined symbol|deriveddata)",
    re.IGNORECASE,
)
NOISE_TERMINAL = re.compile(r"(╭─|╰─|✔ ─╮|pbpaste|pbcopy|\bfind: .*requires)", re.IGNORECASE)
NOISE_DIRECTION = re.compile(
    r"^\s*(was jetzt|was soll ich|was nun|what now|wie weiter|und jetzt"
    r"|langsam was|ok(ay)? (und )?(was|wie)|jetzt genau|wo (soll|stehen|ist)"
    r"|ich bin am (mac|amc)|gib mir|wo genau|was steht)",
    re.IGNORECASE,
)
# Task briefs / work requests the user pasted — not behavioral lessons.
NOISE_TASKBRIEF = re.compile(r"^\s*#\s*(auftrag|klärung|ziel\b|aufgabe)", re.IGNORECASE)
# Opinion / evaluation requests — asking Claude's view, not teaching it.
NOISE_OPINION = re.compile(
    r"^\s*(was denkst du|was hältst du|was meinst du|würdest du|was sagst du"
    r"|was ist das|erkläre mir|kannst du)",
    re.IGNORECASE,
)
# Credential-like strings: must NEVER sit in the inbox. Flagged + archived,
# and surfaced loudly to the user. Patterns are deliberately broad (precision
# over recall is fine here — a false flag just archives one extra block).
SECRET_RE = re.compile(
    r"(censys_[A-Za-z0-9_]{6,}|sk-[A-Za-z0-9]{12,}|bearer\s+[A-Za-z0-9._\-]{12,}"
    r"|\btest_[A-Za-z0-9]{12,}|ghp_[A-Za-z0-9]{20,}|api[ _-]?(token|key)\s*[:=]"
    r"|secret[ _-]?key|password\s*[:=])",
    re.IGNORECASE,
)
# real behavioral signal — if any of these tags is present, lean candidate
SIGNAL_TAGS = {"correction", "omission", "oversight", "anti-pattern", "rule-creation", "denial"}
# tags that alone carry no lesson
WEAK_TAGS = {"positive-confirmation", "halt"}

STOPWORDS = {
    "this", "that", "with", "from", "have", "been", "will", "would", "could",
    "should", "their", "there", "which", "where", "when", "then", "than",
    "what", "your", "more", "into", "some", "only", "such", "also", "very",
    "just", "even", "much", "many", "most", "they", "them", "these", "those",
    "about", "after", "before", "first", "other", "same", "still", "well",
    "make", "made", "take", "given", "find", "found", "soll", "jetzt", "machen",
    "wenn", "dann", "aber", "auch", "nicht", "noch", "schon", "doch", "denn",
    "über", "unter", "mit", "ohne", "bei", "wie", "weil", "damit", "dass",
    "ein", "eine", "einer", "eines", "der", "die", "das", "den", "dem", "des",
    "und", "oder", "sein", "haben", "werden", "können", "müssen", "sollen",
    "wollen", "diese", "dieser", "dieses", "alle", "alles", "nichts", "etwas",
    "immer", "nie", "https", "http", "file", "code", "text", "memory", "name",
}
TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{3,}")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def parse_surprises(text: str) -> list[dict]:
    """Split surprises.md into blocks. Each: {raw, ts, session, tags, cwd, excerpt}."""
    blocks: list[dict] = []
    current: dict | None = None
    lines = text.split("\n")
    header_re = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[([^\]]+)\] (.+)$")
    for line in lines:
        m = header_re.match(line)
        if m:
            if current:
                blocks.append(current)
            current = {
                "ts": m.group(1),
                "session": m.group(2),
                "tags": {t.strip() for t in m.group(3).split(",")},
                "cwd": "",
                "excerpt": "",
                "raw_lines": [line],
            }
            continue
        if current is None:
            continue
        current["raw_lines"].append(line)
        cwd_m = re.match(r"cwd: `([^`]*)`", line)
        if cwd_m:
            current["cwd"] = cwd_m.group(1)
        elif line.startswith("> "):
            current["excerpt"] = line[2:].strip()
    if current:
        blocks.append(current)
    for b in blocks:
        b["raw"] = "\n".join(b["raw_lines"]).rstrip()
    return blocks


def tokenize(text: str) -> Counter:
    return Counter(t.lower() for t in TOKEN_RE.findall(text) if t.lower() not in STOPWORDS)


def signature(excerpt: str) -> str:
    """Normalized signature for recurring-friction detection: strip paths/numbers."""
    s = re.sub(r"/[^\s`'\"]+", "/PATH", excerpt)
    s = re.sub(r"\d+", "N", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s[:80]


# --------------------------------------------------------------------------- #
# Memory corpus (for dup detection) — reuses A-MEM term-overlap idea
# --------------------------------------------------------------------------- #
def build_memory_corpus() -> tuple[dict[str, Counter], dict[str, float]]:
    corpus: dict[str, Counter] = {}
    for path in MEMORY_DIR.glob("*.md"):
        if path.name == "MEMORY.md":
            continue
        try:
            corpus[path.name] = tokenize(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    n = len(corpus) or 1
    df: Counter = Counter()
    for counts in corpus.values():
        df.update(counts.keys())
    idf = {t: math.log(n / (1 + d)) for t, d in df.items()}
    return corpus, idf


def weighted_jaccard(a: Counter, b: Counter, idf: dict[str, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    inter = sum(idf.get(t, 0.0) * min(a[t], b[t]) for t in common)
    union = sum(idf.get(t, 0.0) * max(a.get(t, 0), b.get(t, 0)) for t in (set(a) | set(b)))
    return inter / union if union > 0 else 0.0


def best_memory_match(tokens: Counter, corpus: dict[str, Counter], idf: dict[str, float]):
    best, best_score = None, 0.0
    for fname, counts in corpus.items():
        s = weighted_jaccard(tokens, counts, idf)
        if s > best_score:
            best, best_score = fname, s
    return best, best_score


# --------------------------------------------------------------------------- #
# Stage 1 — classify
# --------------------------------------------------------------------------- #
def classify(blocks: list[dict]) -> None:
    """Annotate each block in place with class_, reason, dup_of, dup_score."""
    corpus, idf = build_memory_corpus()

    # First pass: signature frequency for recurring-friction elevation
    sig_freq: Counter = Counter()
    for b in blocks:
        sig_freq[signature(b["excerpt"])] += 1

    for b in blocks:
        ex = b["excerpt"]
        tags = b["tags"]
        sig = signature(ex)
        b["dup_of"], b["dup_score"] = None, 0.0

        # Secret leak — highest priority. Archived + surfaced; never kept in inbox.
        if SECRET_RE.search(ex):
            b["class_"] = "secret"
            b["reason"] = "credential-like string in inbox (purge)"
            b["sub"] = ""
            continue

        # noise heuristics (content trumps keyword tag)
        if NOISE_BUILD.search(ex):
            noise_reason = "build/compiler error (no behavioral lesson)"
        elif NOISE_TERMINAL.search(ex):
            noise_reason = "terminal paste artifact"
        elif NOISE_TASKBRIEF.search(ex):
            noise_reason = "pasted task brief (work request, not a lesson)"
        elif NOISE_OPINION.search(ex):
            noise_reason = "opinion/eval request (not a correction)"
        elif NOISE_DIRECTION.search(ex):
            noise_reason = "direction-seeking prompt (not a correction)"
        elif tags and tags.issubset(WEAK_TAGS) and not (tags & SIGNAL_TAGS):
            noise_reason = "weak signal only (confirmation/halt, no lesson)"
        else:
            noise_reason = None

        if noise_reason:
            # recurring-friction elevation (ExpeL / Fehler-Synapse)
            if sig_freq[sig] >= RECURRING_THRESHOLD:
                b["class_"] = "candidate"
                b["reason"] = f"recurring-friction ×{sig_freq[sig]} (was: {noise_reason})"
                b["sub"] = "recurring-friction"
                continue
            b["class_"] = "noise"
            b["reason"] = noise_reason
            b["sub"] = ""
            continue

        # dup detection vs memory corpus
        tokens = tokenize(ex)
        if sum(tokens.values()) >= 3:
            fname, score = best_memory_match(tokens, corpus, idf)
            if score >= DUP_SCORE:
                b["class_"], b["reason"] = "dup", f"covered by {fname} (overlap {score:.2f})"
                b["dup_of"], b["dup_score"], b["sub"] = fname, round(score, 3), ""
                continue

        b["class_"] = "candidate"
        b["reason"] = f"genuine signal: {', '.join(sorted(tags & SIGNAL_TAGS)) or 'content'}"
        b["sub"] = ""


# --------------------------------------------------------------------------- #
# Stage 2 — cluster candidates
# --------------------------------------------------------------------------- #
def cluster_candidates(candidates: list[dict]) -> list[dict]:
    """Greedy single-link clustering on weighted-Jaccard of excerpts."""
    if not candidates:
        return []
    toks = [tokenize(c["excerpt"]) for c in candidates]
    n = len(candidates)
    df: Counter = Counter()
    for t in toks:
        df.update(t.keys())
    idf = {t: math.log((n or 1) / (1 + d)) for t, d in df.items()}

    assigned = [-1] * n
    clusters: list[list[int]] = []
    for i in range(n):
        if assigned[i] != -1:
            continue
        cluster = [i]
        assigned[i] = len(clusters)
        for j in range(i + 1, n):
            if assigned[j] != -1:
                continue
            if weighted_jaccard(toks[i], toks[j], idf) >= CLUSTER_SCORE:
                cluster.append(j)
                assigned[j] = len(clusters)
        clusters.append(cluster)

    out = []
    for members in clusters:
        merged: Counter = Counter()
        for idx in members:
            merged.update(toks[idx])
        theme_terms = [t for t, _ in sorted(
            merged.items(), key=lambda kv: idf.get(kv[0], 0) * kv[1], reverse=True)][:5]
        out.append({
            "theme_terms": theme_terms,
            "size": len(members),
            "members": [candidates[idx] for idx in members],
        })
    out.sort(key=lambda c: c["size"], reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def print_table(blocks: list[dict]) -> None:
    counts = Counter(b["class_"] for b in blocks)
    print(f"Triage of {len(blocks)} surprises:\n")
    print(f"  {'class':<10} {'tags':<22} excerpt")
    print(f"  {'-'*10} {'-'*22} {'-'*44}")
    order = {"candidate": 0, "dup": 1, "noise": 2, "secret": 3}
    for b in sorted(blocks, key=lambda x: (order.get(x["class_"], 9), x["ts"])):
        tag_str = ",".join(sorted(b["tags"]))[:21]
        ex = b["excerpt"][:44].replace("\n", " ")
        mark = "★" if b.get("sub") == "recurring-friction" else " "
        print(f" {mark}{b['class_']:<10} {tag_str:<22} {ex}")
    print()
    print(f"  Summary: {counts.get('candidate',0)} candidates · "
          f"{counts.get('dup',0)} dup · {counts.get('noise',0)} noise · "
          f"{counts.get('secret',0)} secret-leak")
    if counts.get("secret"):
        print(f"  ⚠ {counts['secret']} entries contain credential-like strings — "
              f"--apply archives them out of the inbox.")
    elevated = sum(1 for b in blocks if b.get("sub") == "recurring-friction")
    if elevated:
        print(f"  (★ {elevated} elevated from noise via recurring-friction ≥{RECURRING_THRESHOLD})")
    print(f"\n  Dry-run. Re-run with --apply to archive noise+dup and build the cluster digest.")


def write_digest(clusters: list[dict]) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_cand = sum(c["size"] for c in clusters)
    lines = [
        "# Triage Digest — candidate clusters",
        "",
        f"Generated {ts} by surprise_triage.py.",
        f"{n_cand} candidates in {len(clusters)} clusters. Approve in one pass via `/memory-review`.",
        "",
        "Each cluster is a PROPOSED theme — not yet a memory. Human decides per cluster:",
        "promote (write feedback_*.md) · edit · reject.",
        "",
        "---",
        "",
    ]
    for i, c in enumerate(clusters, 1):
        lines.append(f"## Cluster {i} — {' / '.join(c['theme_terms']) or 'misc'}  ({c['size']} items)")
        lines.append("")
        for m in c["members"]:
            sub = f" [{m['sub']}]" if m.get("sub") else ""
            lines.append(f"- `{m['ts']}` ({m['cwd']}){sub}")
            lines.append(f"  > {m['excerpt'][:200]}")
        lines.append("")
    DIGEST.parent.mkdir(parents=True, exist_ok=True)
    DIGEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_triage(text: str, blocks: list[dict]) -> tuple[str, int]:
    """Move noise+dup blocks to .rejected/, keep candidates in surprises.md.
    Returns (new_surprises_text, n_archived). Never deletes."""
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = REJECTED_DIR / f"surprises_triaged_{ts}.md"

    to_archive = [b for b in blocks if b["class_"] in ("noise", "dup", "secret")]
    keep = [b for b in blocks if b["class_"] == "candidate"]

    if to_archive:
        arch_lines = [
            f"# Auto-archived by surprise_triage.py — {ts}",
            "# Reversible: these were classified noise/dup. Move any block back to",
            "# inbox/surprises.md if misclassified.\n",
        ]
        for b in to_archive:
            arch_lines.append(f"<!-- triage: {b['class_']} — {b['reason']} -->")
            arch_lines.append(b["raw"])
            arch_lines.append("")
        with archive.open("a", encoding="utf-8") as f:
            f.write("\n".join(arch_lines) + "\n")

    # Rebuild surprises.md: preserve the original header (everything before first "## ")
    head_match = re.search(r"^## \d{4}-\d{2}-\d{2}", text, re.MULTILINE)
    header = text[: head_match.start()] if head_match else text
    new_text = header.rstrip() + "\n"
    for b in keep:
        new_text += "\n" + b["raw"] + "\n"
    return new_text, len(to_archive)


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="archive noise+dup, keep+cluster candidates")
    ap.add_argument("--json", action="store_true", help="dry-run output as JSON")
    ap.add_argument("--digest-only", action="store_true", help="just rebuild triage_digest.md from current candidates")
    args = ap.parse_args()

    if not SURPRISES.exists():
        print("No surprises.md — nothing to triage.")
        return 0

    text = SURPRISES.read_text(encoding="utf-8")
    blocks = parse_surprises(text)
    if not blocks:
        print("No surprise blocks parsed.")
        return 0

    classify(blocks)
    candidates = [b for b in blocks if b["class_"] == "candidate"]
    clusters = cluster_candidates(candidates)

    if args.json:
        print(json.dumps({
            "total": len(blocks),
            "counts": dict(Counter(b["class_"] for b in blocks)),
            "clusters": [
                {"theme": c["theme_terms"], "size": c["size"],
                 "members": [{"ts": m["ts"], "excerpt": m["excerpt"][:120],
                              "reason": m["reason"]} for m in c["members"]]}
                for c in clusters
            ],
        }, indent=2, ensure_ascii=False))
        return 0

    if args.digest_only:
        write_digest(clusters)
        print(f"Wrote {DIGEST} — {len(clusters)} clusters, {len(candidates)} candidates.")
        return 0

    if not args.apply:
        print_table(blocks)
        return 0

    # --apply
    n_secret = sum(1 for b in blocks if b["class_"] == "secret")
    new_text, n_arch = apply_triage(text, blocks)
    SURPRISES.write_text(new_text, encoding="utf-8")
    write_digest(clusters)
    print(f"Applied: archived {n_arch} (noise+dup+secret) → inbox/.rejected/, "
          f"kept {len(candidates)} candidates in {len(clusters)} clusters.")
    if n_secret:
        print(f"SECRET_LEAK={n_secret}  (credential-like strings archived out of inbox)")
    print(f"CANDIDATES={len(candidates)} CLUSTERS={len(clusters)}")
    print(f"Digest written: {DIGEST}")
    print(f"Next: run /memory-review to approve the clusters in one pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
