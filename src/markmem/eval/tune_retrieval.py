#!/usr/bin/env python3
"""
tune_retrieval.py — Selbst-Tuner fürs Retrieval (Gedächtnis-v3 Frontier).

Schließt die Schleife: das System optimiert seine eigenen RRF-Gewichte UND den
Confidence-Prior gegen die eigene Recall@1-Metrik (Gold-Set aus eval_retrieval
--dump-queries). „Bewährungs-Historie → Rangfolge" + „selbst-abstimmend".

Effizienz: die teuren Signal-Ranglisten (BM25/Entity/Vektor) werden pro Query
GENAU EINMAL berechnet (Vektor-Embed einmalig). Danach durchsucht der Grid nur
noch die Fusion+Confidence in-memory (dict-Ops, kein Ollama) → hunderte Configs/s.

Sicherheit: schreibt die beste Config NUR mit --write. Default = Report (dry).
Übertrifft die beste Config die neutrale Baseline nicht, wird NICHTS geschrieben.
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import product
from pathlib import Path

from markmem.core import memory_retrieve as mr
from markmem.config import MEMORY_DIR
from markmem import paths

MEM = MEMORY_DIR
GOLDSET = paths.EVAL_GOLDSET
OUT = paths.RETRIEVAL_CONFIG

# Suchraum (bm25=1.0 als Referenz fixiert; relativ dazu getunt)
GRID_VECTOR = [0.5, 1.0, 1.5, 2.0, 2.5]
GRID_ENTITY = [0.5, 1.0, 1.5, 2.0]
GRID_BETA = [0.0, 0.3, 0.6, 1.0]
GRID_PENALTY = [1.0, 0.8, 0.6]


def metrics(ranks: list[int | None]) -> tuple[float, float]:
    n = len(ranks) or 1
    r1 = sum(1 for r in ranks if r and r <= 1) / n
    mrr = sum((1.0 / r) for r in ranks if r) / n
    return round(r1, 4), round(mrr, 4)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--goldset", default=str(GOLDSET))
    ap.add_argument("--write", action="store_true", help="beste Config schreiben (sonst nur Report)")
    args = ap.parse_args()

    gs = json.loads(Path(args.goldset).read_text(encoding="utf-8"))
    print(f"[plan] Gold-Set: {len(gs)} (query→gold). Signale werden einmal pro Query berechnet …")

    # Korpus + Signale einmal aufbauen
    tokens, _l, _s = mr.build_corpus()
    bm25 = mr.BM25(tokens)
    entities = mr.load_graph_entities()
    doc_ents = {f: mr.entity_mentions((MEM / f).read_text(encoding="utf-8").lower(), entities)
                for f in tokens} if entities else {}
    conf = mr.load_confidence()
    miscal = mr.load_miscalibrated()

    # Pro Query: (gold, bm_rank, ent_rank, vec_rank) — Vektor-Embed hier EINMAL
    per_q = []
    for i, item in enumerate(gs, 1):
        q, gold = item["query"], item["gold"]
        qt = mr.tokenize(q)
        bm = bm25.rank(qt)
        te = mr.entity_mentions(q.lower(), entities) if entities else set()
        er = mr.entity_rank(te, doc_ents, None) if entities else []
        vr = mr.vector_rank(q.lower(), k=10, exclude=None)
        per_q.append((gold, bm, er, vr))
        if i % 10 == 0:
            print(f"  [signale] {i}/{len(gs)}")

    def eval_cfg(wv, we, beta, pen) -> tuple[float, float]:
        ranks = []
        for gold, bm, er, vr in per_q:
            labeled = [(bm, 1.0), (er, we), (vr, wv)]
            labeled = [(r, w) for r, w in labeled if r]
            fused = mr.rrf_fuse([r for r, _ in labeled], weights=[w for _, w in labeled])

            def cf(f):
                fac = 1.0
                if beta:
                    fac = max(0.5, min(1.5, 1.0 + beta * (conf.get(f, 0.6) - 0.6)))
                if pen != 1.0 and f in miscal:
                    fac *= pen
                return fac
            order = [f for f, _ in sorted(((f, s * cf(f)) for f, s in fused.items()),
                                          key=lambda x: x[1], reverse=True)]
            ranks.append((order.index(gold) + 1) if gold in order else None)
        return metrics(ranks)

    base_r1, base_mrr = eval_cfg(1.0, 1.0, 0.0, 1.0)  # neutrale Baseline
    print(f"\n[baseline] (alle Gewichte 1.0, keine Confidence) Recall@1={base_r1}  MRR={base_mrr}")

    best = (base_r1, base_mrr, 1.0, 1.0, 0.0, 1.0)
    tested = 0
    for wv, we, beta, pen in product(GRID_VECTOR, GRID_ENTITY, GRID_BETA, GRID_PENALTY):
        r1, mrr = eval_cfg(wv, we, beta, pen)
        tested += 1
        if (r1, mrr) > (best[0], best[1]):
            best = (r1, mrr, wv, we, beta, pen)
    r1, mrr, wv, we, beta, pen = best
    print(f"[grid] {tested} Configs getestet.")
    print(f"[best] Recall@1={r1} (Δ{r1-base_r1:+.4f})  MRR={mrr} (Δ{mrr-base_mrr:+.4f})")
    print(f"       weights bm25=1.0 vector={wv} entity={we} · conf_beta={beta} · miscal_penalty={pen}")

    cfg = {"weights": {"bm25": 1.0, "vector": wv, "entity": we},
           "conf_beta": beta, "miscal_penalty": pen,
           "_tuned": {"goldset_n": len(gs), "recall@1": r1, "baseline_recall@1": base_r1}}
    if (r1, mrr) <= (base_r1, base_mrr):
        print("\n[skip] Keine Verbesserung über Baseline — Config NICHT geschrieben (neutral bleibt).")
        return 0
    if args.write:
        OUT.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[write] Beste Config → {OUT}")
    else:
        print(f"\n[dry] Mit --write übernehmen. Vorschlag:\n{json.dumps(cfg, indent=2, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
