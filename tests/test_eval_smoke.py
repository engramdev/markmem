"""
tests/test_eval_smoke.py — Smoke-Test des Retrieval-Eval-Harness.

Im ``--mode desc`` braucht der Harness KEIN LLM (Query = Frontmatter-`description`).
Er läuft über den Demo-Korpus durch und schreibt eine Metrik-Struktur nach
``paths.EVAL_JSON``. Das Vektor-Bein ist ohne Ollama fail-open (CI-tauglich), die
BM25/Entity-Basis reicht für die Smoke-Aussage „der Harness läuft + misst".

Geprüft: Exit 0, Metrik-Struktur (recall@1/3/5 + mrr + n) vorhanden und plausibel.
Ollama ist hier neutralisiert (toter Port), damit der Test deterministisch ist.
"""
from __future__ import annotations

import importlib
import json
import sys

import pytest


@pytest.fixture
def ohne_ollama(monkeypatch):
    monkeypatch.setenv("MARKMEM_OLLAMA_URL", "http://127.0.0.1:1")
    for name in list(sys.modules):
        if name.startswith("markmem."):
            try:
                importlib.reload(sys.modules[name])
            except Exception:
                pass


def test_eval_desc_smoke_laeuft_durch(ohne_ollama, monkeypatch):
    from markmem import paths
    from markmem.eval import eval_retrieval as ev

    # main() via argv treiben: kleiner Stichprobe, desc-Modus (kein LLM).
    monkeypatch.setattr(sys, "argv", ["eval_retrieval", "--mode", "desc", "--n", "8", "--k", "10"])
    rc = ev.main()
    assert rc == 0

    # Metrik-Struktur muss geschrieben worden sein (in den isolierten tmp-Korpus).
    assert paths.EVAL_JSON.exists(), f"erwartete Metrik-Datei {paths.EVAL_JSON}"
    data = json.loads(paths.EVAL_JSON.read_text(encoding="utf-8"))

    assert data["mode"] == "desc"
    assert data["n"] >= 1
    for bein in ("vector_on", "vector_off"):
        m = data[bein]
        for key in ("recall@1", "recall@3", "recall@5", "mrr", "n"):
            assert key in m, f"{bein} fehlt {key}"
        # Plausibilität: Recalls in [0,1].
        assert 0.0 <= m["recall@1"] <= 1.0


def test_eval_score_funktion_direkt(ohne_ollama):
    """Die reine Score-Funktion liefert eine korrekte Metrik-Struktur."""
    from markmem.eval import eval_retrieval as ev

    s = ev.score([1, 2, None, 5, 3])
    assert s["n"] == 5
    assert s["recall@1"] == round(1 / 5, 3)
    assert s["recall@5"] == round(4 / 5, 3)
    assert 0.0 < s["mrr"] <= 1.0


def test_eval_desc_basis_findet_etwas(ohne_ollama):
    """Über den Demo-Korpus sollte die desc-Query mindestens manche Gold-Karte
    in den Top-K finden (BM25 reicht) — beweist, dass der Harness echt misst."""
    from markmem.core import memory_retrieve as mr
    from markmem.eval import eval_retrieval as ev

    cards = ev.sample_cards(8)
    treffer = 0
    for card in cards:
        q = ev.make_query(card, "desc")
        if not q:
            continue
        res = mr.retrieve(mr.tokenize(q), q.lower(), k=10, exclude=None, use_vectors=False)
        if ev.rank_of(card.name, res):
            treffer += 1
    assert treffer >= 1, "BM25 sollte über die description mindestens eine Gold-Karte finden"
