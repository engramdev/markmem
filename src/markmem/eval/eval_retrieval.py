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
import random
import re
import sys
from pathlib import Path

from markmem import paths
from markmem.config import LLM_MODEL, MEMORY_DIR
from markmem.core import llm_client
from markmem.core import memory_retrieve as mr  # retrieve(), tokenize()

MEM = MEMORY_DIR
OUT = paths.EVAL_JSON
FROZEN_OUT = OUT.parent / "eval_frozen.json"  # Frozen-Benchmark-Metriken (neben OUT)
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
    """Observable, fail-open LLM call (shared client)."""
    out = llm_client.generate(prompt, timeout=timeout, temperature=0.4)
    return out.strip() if out is not None else None


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


# ─────────────────────────── Frozen-Benchmark (Ollama-frei) ──────────────────
# Reproduzierbarer, deterministischer Benchmark über einen EINGEFRORENEN Gold-Set
# (query→gold). Kein LLM nötig: die Fragen stehen fest in der JSON, nicht generiert.
# So kann jede*r (und CI) identische Qualitätszahlen über den synthetischen Korpus
# nachrechnen. Das Konfidenzintervall kommt aus einem Bootstrap mit FIXEM Seed
# (stdlib random) → zwei Läufe liefern bit-genau dieselben Zahlen.

def _metric_value(ranks: list[int | None], kind: str) -> float:
    """Ein einzelner Metrik-Wert (recall@k oder mrr) auf einer Rang-Liste."""
    n = len(ranks) or 1
    if kind == "mrr":
        return sum((1.0 / r) for r in ranks if r) / n
    k = int(kind.split("@", 1)[1])
    return sum(1 for r in ranks if r and r <= k) / n


def bootstrap_cis(ranks: list[int | None], k_list=(1, 3, 5), *,
                  resamples: int = 1000, seed: int = 0, alpha: float = 0.05) -> dict:
    """95%-Bootstrap-Konfidenzintervalle je Metrik (Perzentil-Methode).

    Zieht ``resamples`` mal mit Zurücklegen aus den Pro-Query-Rängen und liest die
    (alpha/2, 1-alpha/2)-Perzentile ab. Deterministisch durch ``random.Random(seed)``
    — identischer Seed + identische Eingabe ⇒ bit-genau identische Grenzen. Pure
    stdlib (kein numpy). Gibt ``{metrik: [lo, hi]}`` zurück."""
    kinds = [f"recall@{k}" for k in k_list] + ["mrr"]
    if not ranks:
        return {kind: [0.0, 0.0] for kind in kinds}
    rng = random.Random(seed)
    n = len(ranks)
    acc: dict[str, list[float]] = {kind: [] for kind in kinds}
    for _ in range(resamples):
        sample = [ranks[rng.randrange(n)] for _ in range(n)]
        for kind in kinds:
            acc[kind].append(_metric_value(sample, kind))
    lo_i = int((alpha / 2) * resamples)
    hi_i = int((1 - alpha / 2) * resamples) - 1
    out = {}
    for kind, vals in acc.items():
        vals.sort()
        out[kind] = [round(vals[lo_i], 3), round(vals[hi_i], 3)]
    return out


def load_goldset(path: str | Path) -> list[tuple[str, str]]:
    """Eingefrorenen Gold-Set laden: Liste von (query, gold-Dateiname)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(d["query"], d["gold"]) for d in data]


def frozen_ranks(pairs: list[tuple[str, str]], *, k: int, use_vectors: bool) -> list[int | None]:
    """Für jede (query→gold)-Paarung den Rang der Gold-Karte im Retrieval (oder None)."""
    ranks: list[int | None] = []
    for q, gold in pairs:
        res = mr.retrieve(mr.tokenize(q), q.lower(), k=k, exclude=None, use_vectors=use_vectors)
        ranks.append(rank_of(gold, res))
    return ranks


def run_frozen(goldset_path: str | Path, *, k: int = 10, use_vectors: bool = False) -> dict:
    """Vollständiger Frozen-Lauf: Metriken + 95%-Bootstrap-CI über den Gold-Set.

    Default ``use_vectors=False`` ⇒ Ollama-frei und CI-reproduzierbar. Rein funktional
    (schreibt nichts) — der Report/das Schreiben liegt beim Aufrufer (``main``/Tests)."""
    pairs = load_goldset(goldset_path)
    ranks = frozen_ranks(pairs, k=k, use_vectors=use_vectors)
    return {"n": len(ranks), "k": k, "use_vectors": use_vectors,
            "metrics": score(ranks), "ci95": bootstrap_cis(ranks), "ranks": ranks}


def print_frozen_report(result: dict) -> None:
    m, ci = result["metrics"], result["ci95"]
    leg = "Vektor AN (bge-m3)" if result["use_vectors"] else "BM25+Entity (Ollama-frei)"
    print(f"\n════ Frozen-Benchmark ({leg}, n={result['n']}, k={result['k']}) ════")
    print(f"{'Metrik':<12}{'Wert':>8}{'95%-CI':>20}")
    for kx in ("recall@1", "recall@3", "recall@5", "mrr"):
        lo, hi = ci[kx]
        print(f"{kx:<12}{m[kx]:>8.3f}{f'[{lo:.3f}, {hi:.3f}]':>20}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=25, help="Stichprobengröße (0=alle)")
    ap.add_argument("--mode", choices=["llm", "desc"], default="llm")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--rerank", action="store_true", help="dritte Spalte: Vektor-Pool(20)+Cross-Encoder-Rerank messen")
    ap.add_argument("--pool", type=int, default=20, help="Vektor-Kandidaten vor Rerank")
    ap.add_argument("--dump-queries", help="Gold-Set (query→gold) als JSON speichern und beenden (für tune_retrieval.py, z.B. metrics/eval_goldset.json)")
    ap.add_argument("--goldset", help="Frozen-Modus: eingefrorenen Gold-Set (query→gold JSON) laden, deterministisch messen (kein LLM/Ollama nötig)")
    ap.add_argument("--use-vectors", action="store_true", help="--goldset: zusätzlich das Vektor-Bein messen (braucht Ollama); Default ist Ollama-frei")
    args = ap.parse_args()

    # Frozen-Modus zuerst: kein LLM-Ping, kein Modell-Thrashing — nur deterministisch messen.
    if args.goldset:
        result = run_frozen(args.goldset, k=args.k, use_vectors=args.use_vectors)
        print(f"[plan] Frozen-Benchmark: {result['n']} Paare aus {args.goldset}")
        print_frozen_report(result)
        FROZEN_OUT.parent.mkdir(parents=True, exist_ok=True)
        FROZEN_OUT.write_text(json.dumps({"goldset": str(args.goldset), **result},
                                         indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[done] → {FROZEN_OUT}")
        return 0

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

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"mode": args.mode, "n": len(ranks_on),
                               "vector_on": s_on, "vector_off": s_off,
                               "vector_rerank": s_rr,
                               "vector_decisive": misses}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\n[done] → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
