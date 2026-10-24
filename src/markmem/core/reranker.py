#!/usr/bin/env python3
"""
reranker.py — Cross-Encoder-Reranking (Gedächtnis-v3, optionale Qualitätsstufe).

Nach dem schnellen Vektor-Recall (bge-m3, bi-encoder) ordnet ein Cross-Encoder
(bge-reranker-v2-m3, multilingual DE+EN) die Top-Kandidaten NEU — er sieht Query
und Dokument GEMEINSAM und ist dadurch präziser als reine Vektor-Ähnlichkeit.

Design (sicher/stabil/lean):
  - Nutzt das bereits installierte `transformers`+`torch` (KEIN pip-Install nötig).
  - Lazy-Load, gecacht. FAIL-OPEN: fehlt das Modell / kein Netz / kein torch →
    gibt [] zurück, der Aufrufer behält das ungeränkte Vektor-Ergebnis.
  - OPT-IN: wird nie im latenzkritischen SessionStart-Hook benutzt, nur on-demand
    (memory_retrieve --rerank) + im Eval-Harness. CPU ~100-200ms für Top-20.
  - Erst MESSEN (eval_retrieval.py --rerank), dann adoptieren.

Modell: BAAI/bge-reranker-v2-m3 (~600MB, beim ersten Load aus HF gezogen, dann gecacht).
"""
from __future__ import annotations

from markmem.config import MEMORY_DIR, RERANK_MODEL

MODEL_NAME = RERANK_MODEL
_tok = None
_model = None
_failed = False


def _load():
    """Lazy-Load des Cross-Encoders. Wirft bei Fehler → vom Aufrufer als fail-open behandelt."""
    global _tok, _model, _failed
    if _failed:
        raise RuntimeError("reranker zuvor fehlgeschlagen")
    if _model is None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        _tok = AutoTokenizer.from_pretrained(MODEL_NAME)
        _model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        _model.eval()
    return _tok, _model


def available() -> bool:
    try:
        _load()
        return True
    except Exception:
        global _failed
        _failed = True
        return False


def rerank(query: str, files: list[str], *, k: int = 10,
           doc_chars: int = 2200, max_len: int = 512) -> list[tuple[str, float]]:
    """Ordne `files` (Dateinamen) per Cross-Encoder nach Relevanz zur Query.
    → [(file, score)] Top-k absteigend. Fail-open: [] bei jedem Fehler."""
    try:
        import torch
        tok, model = _load()
    except Exception:
        return []
    docs, valid = [], []
    for f in files:
        try:
            txt = (MEMORY_DIR / f).read_text(encoding="utf-8")[:doc_chars]
        except Exception:
            continue
        docs.append(txt)
        valid.append(f)
    if not docs:
        return []
    try:
        with torch.no_grad():
            inp = tok([[query, d] for d in docs], padding=True, truncation=True,
                      max_length=max_len, return_tensors="pt")
            scores = model(**inp).logits.view(-1).float().tolist()
    except Exception:
        return []
    ranked = sorted(zip(valid, scores), key=lambda x: x[1], reverse=True)
    return ranked[:k]


if __name__ == "__main__":
    import argparse
    import sys

    from markmem.core import vector_store
    ap = argparse.ArgumentParser(description="Vektor-Recall + Cross-Encoder-Rerank (Demo/Test)")
    ap.add_argument("--query", required=True)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--pool", type=int, default=20, help="Vektor-Kandidaten vor Rerank")
    args = ap.parse_args()
    if not available():
        print("[error] Reranker nicht verfügbar (Modell/torch/Netz?).", file=sys.stderr)
        sys.exit(1)
    cands = [f for f, _ in vector_store.search(args.query, k=args.pool)]
    out = rerank(args.query, cands, k=args.k)
    print(f"Rerank für: \"{args.query}\"  ({len(cands)} Kandidaten → Top {len(out)})")
    for f, s in out:
        print(f"  {s:7.3f}  {f}")
