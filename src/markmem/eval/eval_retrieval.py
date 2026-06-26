#!/usr/bin/env python3
"""
eval_retrieval.py — Retrieval-Qualitäts-Harness (Gedächtnis-v3).

"Was man nicht misst, kann man nicht optimieren." Dieser Harness misst, wie gut
das Gedächtnis die RICHTIGE Karte findet — und ob das Vektor-Bein das messbar
verbessert (A/B). Damit werden Reranker/Chunking/Modell-Wechsel beweisbar statt
geraten.

Methode (innovativ + ehrlich): für eine Stichprobe Karten erzeugt ein lokales LLM
eine PARAPHRASIERTE Frage — bewusst OHNE die exakten Schlüsselwörter der Karte.
So kann reines BM25 (Wort-Überlappung) nicht „schummeln"; nur echtes Bedeutungs-
Verständnis (Vektor) findet die Karte. Gemessen: Recall@1/3/5 + MRR, je für
Vektor-AN vs Vektor-AUS auf identischen Queries.

Deterministischer Fallback (--mode desc): Query = Frontmatter-`description` (kein LLM).

Output: metrics/eval_retrieval.json (Verlauf trackbar) + Konsolen-Report.
Read-only ggü. Memory. Nutzt memory_retrieve.retrieve() programmatisch.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

from markmem.core import memory_retrieve as mr  # retrieve(), tokenize()
from markmem.config import MEMORY_DIR, OLLAMA_URL, LLM_MODEL
from markmem import paths

MEM = MEMORY_DIR
OUT = paths.EVAL_JSON
SKIP = paths.SKIP_FILES

DESC_RE = re.compile(r"^description:\s*(.*)", re.MULTILINE)
PARAPHRASE_PROMPT = (
    "Hier ist der Anfang einer Wissens-Notiz aus einer Bug-Bounty-Wissensbasis:\n\n"
    "{content}\n\n"
    "Formuliere EINE kurze, natürliche deutsche Frage (max 15 Wörter), die genau diese "
    "Notiz beantworten würde. WICHTIG: vermeide die auffälligsten Eigennamen/Fachbegriffe "
    "der Notiz — umschreibe sie. Antworte NUR mit der Frage, sonst nichts."
)


def llm(prompt: str, timeout: int = 60) -> str | None:
    payload = json.dumps({"model": LLM_MODEL, "prompt": prompt, "stream": False,
                          "options": {"temperature": 0.4}}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()).get("response", "").strip()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def sample_cards(n: int) -> list[Path]:
    """Deterministische Stichprobe (jede k-te Karte) — reproduzierbar, kein Random."""
    cards = sorted(p for p in MEM.glob("*.md") if p.name not in SKIP)
    if n <= 0 or n >= len(cards):
        return cards
    step = len(cards) / n
    return [cards[int(i * step)] for i in range(n)]


def make_query(card: Path, mode: str) -> str | None:
    text = card.read_text(encoding="utf-8")
    if mode == "desc":
        m = DESC_RE.search(text)
        return m.group(1).strip() if m else None
    # llm-Paraphrase aus einem KURZEN Seed (Description + Karten-Anfang) — kurz =
    # schnelle dolphin-Inferenz auf CPU (langer Input war der Engpass).
    body = re.sub(r"^---.*?---", "", text, count=1, flags=re.DOTALL).strip()
    dm = DESC_RE.search(text)
    seed = ((dm.group(1).strip() + " — ") if dm else "") + body[:200]
    q = llm(PARAPHRASE_PROMPT.format(content=seed[:320]))
    if not q:
        return None
    q = q.splitlines()[0].strip().strip('"').strip()
    return q or None


def rank_of(gold: str, results: list[dict]) -> int | None:
    for i, r in enumerate(results, 1):
        if r["file"] == gold:
            return i
    return None


def score(ranks: list[int | None], k_list=(1, 3, 5)) -> dict:
    n = len(ranks) or 1
    out = {f"recall@{k}": round(sum(1 for r in ranks if r and r <= k) / n, 3) for k in k_list}
    out["mrr"] = round(sum((1.0 / r) for r in ranks if r) / n, 3)
    out["found_any"] = sum(1 for r in ranks if r)
    out["n"] = len(ranks)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=25, help="Stichprobengröße (0=alle)")
    ap.add_argument("--mode", choices=["llm", "desc"], default="llm")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--rerank", action="store_true", help="dritte Spalte: Vektor-Pool(20)+Cross-Encoder-Rerank messen")
    ap.add_argument("--pool", type=int, default=20, help="Vektor-Kandidaten vor Rerank")
    ap.add_argument("--dump-queries", help="Gold-Set (query→gold) als JSON speichern und beenden (für tune_retrieval.py, z.B. metrics/eval_goldset.json)")
    args = ap.parse_args()

    rr = None
    if args.rerank:
        from markmem.core import reranker as rr
        if not rr.available():
            print("[error] --rerank: Reranker nicht verfügbar.", file=sys.stderr)
            return 1

    if args.mode == "llm" and llm("ping", timeout=120) is None:
        print(f"[error] LLM {LLM_MODEL} nicht erreichbar.", file=sys.stderr)
        return 1

    cards = sample_cards(args.n)
    print(f"[plan] {len(cards)} Karten, mode={args.mode} — A/B Vektor an vs aus.")

    # PHASE 1: alle Queries generieren (nur dolphin im RAM — kein Modell-Thrashing)
    pairs: list[tuple[Path, str]] = []
    for i, card in enumerate(cards, 1):
        q = make_query(card, args.mode)
        if q:
            pairs.append((card, q))
        if args.mode == "llm" and i % 5 == 0:
            print(f"  [gen] {i}/{len(cards)} Queries")

    if args.dump_queries:
        data = [{"query": q, "gold": card.name} for card, q in pairs]
        Path(args.dump_queries).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[dump] {len(data)} (query→gold)-Paare → {args.dump_queries}")
        return 0

    # PHASE 2: alle Retrievals (jetzt nur bge-m3 im RAM — ein einziger Modell-Swap)
    ranks_on: list[int | None] = []
    ranks_off: list[int | None] = []
    ranks_rr: list[int | None] = []
    misses = []
    for i, (card, q) in enumerate(pairs, 1):
        qt = mr.tokenize(q)
        r_on = mr.retrieve(qt, q.lower(), k=max(args.k, args.pool), exclude=None, use_vectors=True)
        r_off = mr.retrieve(qt, q.lower(), k=args.k, exclude=None, use_vectors=False)
        ron, roff = rank_of(card.name, r_on[:args.k]), rank_of(card.name, r_off)
        ranks_on.append(ron)
        ranks_off.append(roff)
        if rr is not None:
            pool = [x["file"] for x in r_on[:args.pool]]
            reranked = rr.rerank(q, pool, k=args.k)
            rrank = rank_of(card.name, [{"file": f} for f, _ in reranked])
            ranks_rr.append(rrank)
        if (roff is None or roff > 5) and ron and ron <= 5:
            misses.append({"card": card.name, "query": q, "rank_off": roff, "rank_on": ron})
        if i % 5 == 0:
            print(f"  [retr] {i}/{len(pairs)}")

    s_on, s_off = score(ranks_on), score(ranks_off)
    s_rr = score(ranks_rr) if rr is not None else None
    print("\n════ Retrieval-Qualität ════")
    if s_rr is None:
        print(f"{'Metrik':<12}{'Vektor AUS':>12}{'Vektor AN':>12}{'Δ':>10}")
        for kx in ("recall@1", "recall@3", "recall@5", "mrr"):
            print(f"{kx:<12}{s_off[kx]:>12.3f}{s_on[kx]:>12.3f}{s_on[kx]-s_off[kx]:>+10.3f}")
    else:
        print(f"{'Metrik':<12}{'Vektor AUS':>12}{'Vektor AN':>12}{'+Rerank':>12}{'Δ(rr-an)':>10}")
        for kx in ("recall@1", "recall@3", "recall@5", "mrr"):
            print(f"{kx:<12}{s_off[kx]:>12.3f}{s_on[kx]:>12.3f}{s_rr[kx]:>12.3f}{s_rr[kx]-s_on[kx]:>+10.3f}")
    print(f"\nVektor war entscheidend (off verfehlt→on findet, top5): {len(misses)} Fälle")
    for m in misses[:6]:
        print(f"  • {m['card']}  (off {m['rank_off']} → on #{m['rank_on']})")
        print(f"    q: \"{m['query']}\"")

    OUT.write_text(json.dumps({"mode": args.mode, "n": len(ranks_on),
                               "vector_on": s_on, "vector_off": s_off,
                               "vector_rerank": s_rr,
                               "vector_decisive": misses}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\n[done] → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
