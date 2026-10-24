#!/usr/bin/env python3
"""
memory_retrieve.py — Multi-Signal Retrieval-Fusion für den Memory-Pool.

Hebt das Recall vom reinen Jaccard (find_related_memories.py) auf eine Fusion
mehrerer unabhängiger Signale — adaptiert von Mem0s Fusion-Retrieval-Rezept
(semantic + lexical + entity, parallel gescored, dann fusioniert).

Signale (alle pure-stdlib, keine externen Dependencies = stabil/offline):
  1. BM25      — lexikalisches Ranking (ersetzt naives Jaccard; berücksichtigt
                 Term-Frequenz, Doc-Länge, IDF — robuster als Set-Overlap).
  2. ENTITY    — geteilte Graph-Entitäten aus dem memory-graph (graph.json).
                 Zwei Memories, die dieselbe Target/Auth-Methode/Entität nennen,
                 gehören zusammen, auch wenn die Worte sonst divergieren.
  3. (SEMANTIC — Embedding-Signal lebt im claude-context MCP / /memory-search;
                 wird im Slash-Command-Flow per RRF dazugemischt, siehe --rrf-in.)

Fusion: Reciprocal Rank Fusion (RRF, K=60). Rang-basiert statt Score-Addition →
robust gegen unterschiedliche Score-Skalen der Signale (Standard-Verfahren).

Aufruf:
  memory_retrieve.py <slug|file>          # verwandte zu existierender Memory
  memory_retrieve.py --query "free text"  # Ad-hoc-Suche
  echo "<entwurf>" | memory_retrieve.py --text   # Dedup vor Neuanlage
  Flags: --k N  --json  --explain  --rrf-in <file.json>

Exit: 0 ok, 1 Fehler. Read-only, schreibt nie.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from markmem.config import MEMORY_DIR, GRAPH
from markmem import paths

RETRIEVAL_CONFIG = paths.RETRIEVAL_CONFIG  # versioniert (verhaltensbestimmend)
INDEX_CACHE = paths.INDEX_CACHE
KALIB_FILE = paths.KALIB_FILE

# Default = neutral (= bisheriges Verhalten). Erst wenn der Selbst-Tuner eine bessere
# Config schreibt, ändert sich etwas → backward-compatible + risikofrei.
DEFAULT_CONFIG = {
    "weights": {"bm25": 1.0, "entity": 1.0, "vector": 1.0},
    "conf_beta": 0.0,        # 0 = Confidence ignoriert; >0 = bewährte Karten ranken höher
    "miscal_penalty": 1.0,   # <1 = miskalibrierte Karten ranken runter
}


def load_config() -> dict:
    """Retrieval-Config (vom Selbst-Tuner geschrieben). Fail-safe auf Defaults."""
    cfg = {**DEFAULT_CONFIG, "weights": dict(DEFAULT_CONFIG["weights"])}
    try:
        c = json.loads(RETRIEVAL_CONFIG.read_text(encoding="utf-8"))
        if isinstance(c.get("weights"), dict):
            cfg["weights"].update({k: float(v) for k, v in c["weights"].items()})
        for key in ("conf_beta", "miscal_penalty"):
            if key in c:
                cfg[key] = float(c[key])
    except Exception:
        pass
    return cfg


def load_confidence() -> dict[str, float]:
    """file → confidence (aus dem Index-Cache-Frontmatter). Lern-Signal: bewährte Karten."""
    try:
        cache = json.loads(INDEX_CACHE.read_text(encoding="utf-8"))
        out = {}
        for f, m in cache.get("memories", {}).items():
            try:
                out[f] = float(m.get("confidence", 0.6) or 0.6)
            except (ValueError, TypeError):
                out[f] = 0.6
        return out
    except Exception:
        return {}


def load_miscalibrated() -> set[str]:
    """Karten, deren Confidence in Outcomes fiel (Rat trog) — Kalibrierungs-Schicht."""
    try:
        return {m["memory"] for m in json.loads(KALIB_FILE.read_text(encoding="utf-8")).get("miscalibrated", [])}
    except Exception:
        return set()

# Helfer aus dem bestehenden Linker wiederverwenden (Single Source of Truth für
# Tokenisierung/Stopwords/Korpus). Fällt auf lokale Kopie zurück, falls Import bricht.
try:
    from markmem.core.find_related_memories import tokenize, build_corpus  # type: ignore
except Exception:  # pragma: no cover — defensiv, sollte nie feuern
    TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{3,}")
    _STOP = {"this", "that", "with", "from", "nicht", "oder", "und", "der", "die", "das"}

    def tokenize(text: str) -> Counter:  # type: ignore
        return Counter(t.lower() for t in TOKEN_RE.findall(text) if t.lower() not in _STOP)

    def build_corpus():  # type: ignore
        tokens, links, slug_to_file = {}, {}, {}
        wl = re.compile(r"\[\[([a-zA-Z0-9_\-]+)\]\]")
        nf = re.compile(r"^name:\s*(\S+)", re.MULTILINE)
        for p in MEMORY_DIR.glob("*.md"):
            if p.name == "MEMORY.md":
                continue
            try:
                txt = p.read_text(encoding="utf-8")
            except Exception:
                continue
            tokens[p.name] = tokenize(txt)
            links[p.name] = set(wl.findall(txt))
            m = nf.search(txt)
            if m:
                slug_to_file[m.group(1)] = p.name
        return tokens, links, slug_to_file


# ---------------------------------------------------------------- BM25 --------
class BM25:
    """Klassisches BM25 (k1=1.5, b=0.75) über vortokenisierte Counter."""

    def __init__(self, corpus: dict[str, Counter], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = corpus
        self.doc_len = {f: sum(c.values()) for f, c in corpus.items()}
        n = len(corpus) or 1
        self.avgdl = (sum(self.doc_len.values()) / n) if n else 0.0
        df: Counter = Counter()
        for c in corpus.values():
            df.update(c.keys())
        # BM25-IDF mit +1 (immer positiv, kein negativer Beitrag häufiger Terme)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def score(self, query_terms: Counter, fname: str) -> float:
        c = self.docs[fname]
        dl = self.doc_len[fname] or 1
        denom_len = self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
        s = 0.0
        for t in query_terms:
            f = c.get(t, 0)
            if not f:
                continue
            s += self.idf.get(t, 0.0) * (f * (self.k1 + 1)) / (f + denom_len)
        return s

    def rank(self, query_terms: Counter, exclude: str | None = None) -> list[tuple[str, float]]:
        out = []
        for f in self.docs:
            if f == exclude:
                continue
            sc = self.score(query_terms, f)
            if sc > 0:
                out.append((f, sc))
        out.sort(key=lambda x: x[1], reverse=True)
        return out


# ------------------------------------------------------------- ENTITY ---------
def load_graph_entities() -> list[str]:
    """Entity-Namen + Alias-Beobachtungs-Begriffe aus dem memory-graph (JSONL).
    Fail-open: leerer Graph → [] (Entity-Signal trägt dann einfach 0 bei)."""
    if not GRAPH.exists():
        return []
    names: set[str] = set()
    try:
        for line in GRAPH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") == "entity":
                nm = str(o.get("name", "")).strip().lower()
                if len(nm) >= 3:
                    names.add(nm)
    except Exception:
        return []
    return sorted(names)


def entity_mentions(text_lower: str, entities: list[str]) -> set[str]:
    """Welche Graph-Entitäten nennt dieser Memory-Text? (Wort-/Teilstring-Match
    auf Entity-Namen; mehrteilige Namen via Bestandteile.)"""
    hits = set()
    for ent in entities:
        # mehrteilige Entity-Namen: alle signifikanten Teile (≥4 Zeichen, wie der
        # Tokenizer) müssen vorkommen. ≥4 verhindert, dass generische Kurz-Teile
        # wie "one" (aus "w-one") gegen halb den Korpus matchen.
        parts = [p for p in re.split(r"[\s_\-]+", ent) if len(p) >= 4]
        if parts and all(p in text_lower for p in parts):
            hits.add(ent)
    return hits


def entity_rank(target_ents: set[str], doc_ents: dict[str, set[str]],
                exclude: str | None) -> list[tuple[str, float]]:
    if not target_ents:
        return []
    out = []
    for f, ents in doc_ents.items():
        if f == exclude:
            continue
        shared = target_ents & ents
        if shared:
            out.append((f, float(len(shared))))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


# ------------------------------------------------------------- VECTOR ---------
def vector_rank(query_text: str, *, k: int,
                exclude: str | None) -> tuple[list[tuple[str, float]], str]:
    """Semantik-Bein (bge-m3 via vector_store, embedded SQLite + numpy-Cosine).
    Liefert (rankings, leg_status) mit leg_status in {"ok", "unavailable"}.
    Fail-open: bei fehlendem Index/Ollama/numpy -> ([], "unavailable"), das System
    läuft mit BM25+Entity weiter (kein Crash, kein Hook-Timeout). "unavailable"
    unterscheidet 'Bein tot' von 'Bein fand nichts' — beide lieferten sonst []."""
    try:
        from markmem.core import vector_store  # type: ignore
    except ImportError:
        return [], "unavailable"
    if not vector_store.available():
        return [], "unavailable"
    before = vector_store.stats()
    try:
        res = vector_store.search(query_text, k=max(k * 3, 30), exclude=exclude)
    except Exception:
        return [], "unavailable"
    # Zählte das Embedding während DIESER Suche einen Fehler? -> Ollama tot trotz Index.
    if any(vector_store.stats()[key] > before[key] for key in before):
        return [], "unavailable"
    return res, "ok"


def rerank_files(query_text: str, files: list[str], k: int) -> list[tuple[str, float]]:
    """Optionale Qualitätsstufe: Cross-Encoder (bge-reranker-v2-m3) ordnet die
    Top-Kandidaten neu. Gemessen (eval n=30): Recall@1 0.87→0.93. Fail-open: []
    wenn Modell/torch fehlt → Aufrufer behält die RRF-Reihenfolge. NICHT im Hook
    (CPU ~150ms) — nur on-demand via --rerank."""
    try:
        from markmem.core import reranker  # type: ignore
        return reranker.rerank(query_text, files, k=k)
    except Exception:
        return []


# --------------------------------------------------------------- RRF ----------
def rrf_fuse(rankings: list[list[tuple[str, float]]], k: int = 60,
             weights: list[float] | None = None) -> dict[str, float]:
    """Reciprocal Rank Fusion mit optionalen Per-Signal-Gewichten. rankings = Liste
    von [(fname, score)], bereits sortiert. weights parallel zu rankings (Default 1.0).
    Die Gewichte werden vom Selbst-Tuner (tune_retrieval.py) gegen die Eval-Metrik optimiert."""
    fused: dict[str, float] = defaultdict(float)
    for idx, ranking in enumerate(rankings):
        w = weights[idx] if (weights and idx < len(weights)) else 1.0
        for rank, (fname, _score) in enumerate(ranking, start=1):
            fused[fname] += w * (1.0 / (k + rank))
    return fused


# -------------------------------------------------------------- CORE ----------
def retrieve(query_terms: Counter, query_text_lower: str, *, k: int,
             exclude: str | None, extra_rankings: list[list[tuple[str, float]]] | None = None,
             use_vectors: bool = True, rerank: bool = False, rerank_pool: int = 20,
             config: dict | None = None,
             with_status: bool = False) -> list[dict] | tuple[list[dict], dict]:
    tokens, _links, _slug = build_corpus()
    bm25 = BM25(tokens)
    entities = load_graph_entities()
    doc_ents = {f: entity_mentions((MEMORY_DIR / f).read_text(encoding="utf-8").lower(), entities)
                for f in tokens} if entities else {}

    bm_rank = bm25.rank(query_terms, exclude=exclude)
    target_ents = entity_mentions(query_text_lower, entities) if entities else set()
    ent_rank = entity_rank(target_ents, doc_ents, exclude) if entities else []
    if use_vectors:
        vec_rank, vec_leg = vector_rank(query_text_lower, k=k, exclude=exclude)
    else:
        vec_rank, vec_leg = [], "disabled"

    cfg = config if config is not None else load_config()
    w = cfg["weights"]
    # (ranking, gewicht) gepaart, DANN leere filtern → Gewichte bleiben ausgerichtet
    labeled = [(bm_rank, w.get("bm25", 1.0)), (ent_rank, w.get("entity", 1.0)),
               (vec_rank, w.get("vector", 1.0))]
    if extra_rankings:
        labeled += [(r, 1.0) for r in extra_rankings]
    labeled = [(r, wt) for r, wt in labeled if r]
    fused = rrf_fuse([r for r, _ in labeled], weights=[wt for _, wt in labeled])

    # Confidence-Prior (Lern-Schleife → Rangfolge): bewährte Karten hoch, miskalibrierte runter
    beta = float(cfg.get("conf_beta", 0.0))
    pen = float(cfg.get("miscal_penalty", 1.0))
    conf = load_confidence() if beta != 0.0 else {}
    miscal = load_miscalibrated() if (beta != 0.0 or pen != 1.0) else set()

    def conf_factor(f: str) -> float:
        fac = 1.0
        if beta != 0.0:
            fac = max(0.5, min(1.5, 1.0 + beta * (conf.get(f, 0.6) - 0.6)))
        if pen != 1.0 and f in miscal:
            fac *= pen
        return fac

    bm_pos = {f: i + 1 for i, (f, _) in enumerate(bm_rank)}
    ent_pos = {f: i + 1 for i, (f, _) in enumerate(ent_rank)}
    vec_pos = {f: i + 1 for i, (f, _) in enumerate(vec_rank)}
    bm_score = dict(bm_rank)
    vec_score = dict(vec_rank)

    ranked_fused = sorted(((f, s * conf_factor(f)) for f, s in fused.items()),
                          key=lambda x: x[1], reverse=True)

    # Optionaler Cross-Encoder-Rerank über die Top-Kandidaten (fail-open → RRF-Reihenfolge)
    rer = rerank_files(query_text_lower, [f for f, _ in ranked_fused[:rerank_pool]], k) if rerank else []
    rer_score = dict(rer)
    rer_pos = {f: i + 1 for i, (f, _) in enumerate(rer)}
    if rer:
        order = [f for f, _ in rer]
        rest = [f for f, _ in ranked_fused if f not in rer_pos]
        final_files = (order + rest)[:k]
    else:
        final_files = [f for f, _ in ranked_fused[:k]]

    results = []
    for fname in final_files:
        results.append({
            "file": fname,
            "rrf": round(fused.get(fname, 0.0), 5),
            "bm25_rank": bm_pos.get(fname),
            "bm25_score": round(bm_score.get(fname, 0.0), 3),
            "entity_rank": ent_pos.get(fname),
            "vector_rank": vec_pos.get(fname),
            "vector_score": round(vec_score.get(fname, 0.0), 4),
            "rerank_rank": rer_pos.get(fname) if rer else None,
            "rerank_score": round(rer_score.get(fname, 0.0), 3) if rer else None,
            "shared_entities": sorted((target_ents & doc_ents.get(fname, set()))) if entities else [],
        })
    if with_status:
        return results, {"degraded": vec_leg == "unavailable", "vector_leg": vec_leg}
    return results


def slug_or_file_to_name(target: str) -> str | None:
    _t, _l, slug_to_file = build_corpus()
    if not target.endswith(".md"):
        return slug_to_file.get(target) or (f"{target}.md" if (MEMORY_DIR / f"{target}.md").exists() else None)
    return target if (MEMORY_DIR / target).exists() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="slug oder Dateiname einer Memory")
    ap.add_argument("--query", help="Ad-hoc-Freitext-Suche statt Memory-Target")
    ap.add_argument("--text", action="store_true", help="Dedup-Modus: Entwurf von stdin")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--rrf-in", help="JSON-Datei mit zusätzlichem Ranking [[file,score],...] (z.B. Semantik aus /memory-search)")
    ap.add_argument("--no-vectors", action="store_true", help="Semantik-Bein (bge-m3) deaktivieren — nur BM25+Entity")
    ap.add_argument("--rerank", action="store_true", help="Cross-Encoder-Rerank (bge-reranker-v2-m3) der Top-Kandidaten — +Präzision, ~150ms CPU")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--explain", action="store_true", help="zeige Pro-Signal-Ränge")
    args = ap.parse_args()

    extra = None
    if args.rrf_in:
        try:
            raw = json.loads(Path(args.rrf_in).read_text(encoding="utf-8"))
            extra = [[(str(x[0]), float(x[1])) for x in raw]]
        except Exception as e:
            print(f"[warn] --rrf-in ignoriert ({e})", file=sys.stderr)

    exclude = None
    if args.text:
        text = sys.stdin.read()
        if not text.strip():
            print("[error] --text: kein Text auf stdin", file=sys.stderr)
            return 1
    elif args.query:
        text = args.query
    elif args.target:
        fname = slug_or_file_to_name(args.target)
        if not fname:
            print(f"[error] target nicht gefunden: {args.target}", file=sys.stderr)
            return 1
        exclude = fname
        text = (MEMORY_DIR / fname).read_text(encoding="utf-8")
    else:
        ap.error("target ODER --query ODER --text erforderlich")

    qterms = tokenize(text)
    use_vectors = not args.no_vectors
    results, status = retrieve(qterms, text.lower(), k=args.k, exclude=exclude,
                               extra_rankings=extra, use_vectors=use_vectors,
                               rerank=args.rerank, with_status=True)

    if args.json:
        fusion = ["bm25", "entity"] + (["vector"] if use_vectors else []) + (["external-rrf"] if extra else []) + (["rerank"] if args.rerank else [])
        print(json.dumps({"query": exclude or args.query or "stdin-draft",
                          "fusion": fusion,
                          "degraded": status["degraded"],
                          "vector_leg": status["vector_leg"],
                          "results": results}, indent=2, ensure_ascii=False))
        return 0

    label = exclude or (args.query and f'"{args.query}"') or "stdin-Entwurf"
    print(f"Fusion-Retrieval für: {label}")
    print("Signale: BM25 + Entity-Graph" + (" + Vektor(bge-m3)" if use_vectors else "")
          + (" + extern(RRF)" if extra else ""))
    print()
    rr_hdr = f"  {'rr':>4}" if args.rerank else ""
    print(f"{'rrf':>7}  {'bm25':>5}  {'ent':>4}  {'vec':>4}{rr_hdr}  file")
    print(f"{'-------':>7}  {'-----':>5}  {'----':>4}  {'----':>4}{'  ----' if args.rerank else ''}  {'-' * 40}")
    for r in results:
        bm = f"#{r['bm25_rank']}" if r["bm25_rank"] else "-"
        en = f"#{r['entity_rank']}" if r["entity_rank"] else "-"
        ve = f"#{r['vector_rank']}" if r.get("vector_rank") else "-"
        rrc = (f"  {('#'+str(r['rerank_rank'])) if r.get('rerank_rank') else '-':>4}") if args.rerank else ""
        print(f"  {r['rrf']:.4f}  {bm:>5}  {en:>4}  {ve:>4}{rrc}  {r['file']}")
        if args.explain and r["shared_entities"]:
            print(f"           ↳ entities: {', '.join(r['shared_entities'][:5])}")
    if status["degraded"]:
        print("\n(degraded: vector leg unavailable -- BM25+entity only. "
              "Start ollama / run markmem-index to enable semantic recall.)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
