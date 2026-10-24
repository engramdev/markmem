"""
tests/test_retrieve_failopen.py — Fail-open des Semantik-Beins.

Wenn Ollama nicht erreichbar ist (hier: toter Port http://127.0.0.1:1), MUSS:
  * ``vector_store.search`` sauber ``[]`` zurückgeben (kein Crash, kein Hang),
  * ``memory_retrieve.retrieve(..., use_vectors=True)`` trotzdem Ergebnisse liefern
    (BM25 + Entity tragen die Last) — das System bleibt funktionsfähig ohne Ollama.

Das ist die Garantie, dass die CI (kein Ollama) grün bleibt und Produktions-Hooks
nie an einem fehlenden Embedding-Server hängen bleiben.
"""
from __future__ import annotations

import pytest

DEAD_OLLAMA = "http://127.0.0.1:1"  # Port 1 → Connection refused, sofort


@pytest.fixture
def totes_ollama(monkeypatch):
    """OLLAMA_URL auf toten Port + markmem-Module neu laden, damit config/vector_store
    die URL übernehmen."""
    import importlib
    import sys

    monkeypatch.setenv("MARKMEM_OLLAMA_URL", DEAD_OLLAMA)
    # config + alle markmem-Submodule, die OLLAMA_URL als Konstante kopieren, neu laden.
    for name in ("markmem.config", "markmem.paths"):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    for name in list(sys.modules):
        if name.startswith("markmem.") and name not in ("markmem.config", "markmem.paths"):
            try:
                importlib.reload(sys.modules[name])
            except Exception:
                pass


def test_vector_store_search_gibt_leer_bei_totem_ollama(totes_ollama):
    from markmem.core import vector_store

    # Kurzer Timeout — selbst falls ein Index existierte, scheitert das Embedding
    # am toten Port und search() liefert fail-open [].
    res = vector_store.search("widget api rate limit", k=5, timeout=2)
    assert res == [], f"erwartet [], bekam {res!r}"


def test_retrieve_failopen_liefert_trotzdem_ergebnisse(totes_ollama):
    from markmem.core import memory_retrieve as mr

    q = "cache invalidation stale entries widget"
    qterms = mr.tokenize(q)
    results = mr.retrieve(qterms, q.lower(), k=5, exclude=None, use_vectors=True)

    assert results, "BM25/Entity sollten auch ohne Vektor-Bein Treffer liefern"
    assert all("file" in r for r in results)
    # Das Vektor-Bein darf zu keinem Treffer beitragen (alle vector_rank = None),
    # weil Ollama tot ist — beweist, dass die Ergebnisse aus BM25/Entity stammen.
    assert all(r.get("vector_rank") is None for r in results), \
        "ohne Ollama sollte kein Vektor-Rang gesetzt sein"


def test_retrieve_use_vectors_false_identisch_failopen(totes_ollama):
    """use_vectors=False (explizit aus) vs. use_vectors=True bei totem Ollama:
    beide dürfen nicht crashen und liefern dieselbe BM25/Entity-Basis."""
    from markmem.core import memory_retrieve as mr

    q = "deploy pipeline staging gate rollback"
    qterms = mr.tokenize(q)
    r_on = mr.retrieve(qterms, q.lower(), k=5, exclude=None, use_vectors=True)
    r_off = mr.retrieve(qterms, q.lower(), k=5, exclude=None, use_vectors=False)
    assert r_on and r_off
    assert [r["file"] for r in r_on] == [r["file"] for r in r_off]


# --------------------------- degraded-Selbstauskunft (with_status) ------------
def test_with_status_meldet_degraded_bei_totem_ollama(totes_ollama):
    """with_status=True: bei totem Ollama (bzw. ohne Index) MUSS degraded=True und
    vector_leg='unavailable' gemeldet werden -- die ehrliche Selbstauskunft, dass
    diese Antwort ohne Semantik-Bein lief."""
    from markmem.core import memory_retrieve as mr

    q = "cache invalidation stale entries widget"
    results, status = mr.retrieve(mr.tokenize(q), q.lower(), k=5, exclude=None,
                                  use_vectors=True, with_status=True)
    assert results  # BM25/Entity tragen weiter
    assert status["degraded"] is True
    assert status["vector_leg"] == "unavailable"


def test_with_status_use_vectors_false_ist_disabled_nicht_degraded(totes_ollama):
    """Vektor-Bein bewusst aus ist KEINE Degradierung -- 'disabled', degraded=False."""
    from markmem.core import memory_retrieve as mr

    q = "deploy pipeline staging gate rollback"
    _results, status = mr.retrieve(mr.tokenize(q), q.lower(), k=5, exclude=None,
                                   use_vectors=False, with_status=True)
    assert status["vector_leg"] == "disabled"
    assert status["degraded"] is False


def test_default_ohne_status_bleibt_reine_liste(totes_ollama):
    """Backward-Compat: with_status=False (Default) liefert weiter eine reine Liste --
    kein bestehender Aufrufer bricht."""
    from markmem.core import memory_retrieve as mr

    q = "widget api rate limit"
    out = mr.retrieve(mr.tokenize(q), q.lower(), k=5, exclude=None, use_vectors=True)
    assert isinstance(out, list)
    assert all(isinstance(r, dict) for r in out)


def test_vector_store_available_returns_bool(totes_ollama):
    from markmem.core import vector_store

    assert isinstance(vector_store.available(), bool)


def test_vector_rank_contract_returns_list_and_status(totes_ollama):
    """Signatur-Vertrag, auf den ALLE Aufrufer (memory_retrieve, tune_retrieval)
    bauen: vector_rank -> (list, status-str). Schützt vor stiller Regression wie
    der, die den Tuner brach."""
    from markmem.core import memory_retrieve as mr

    out = mr.vector_rank("widget api", k=5, exclude=None)
    assert isinstance(out, tuple) and len(out) == 2
    rankings, leg = out
    assert isinstance(rankings, list)
    assert leg in {"ok", "unavailable"}
