"""
tests/test_vector_ollama.py — OPT-IN Tests des echten Semantik-Beins (Ollama/bge-m3).

Diese Tests brauchen einen laufenden Ollama mit gezogenem ``bge-m3`` und sind deshalb
mit ``@pytest.mark.ollama`` markiert. Die CI (``-m "not ollama and not rerank"``) schließt
sie aus. Lokal (Ollama vorhanden) laufen sie grün; ist Ollama NICHT erreichbar, wird
sauber geskippt — nie ein Fehlschlag.

Sie ergänzen die fail-open-Tests (test_retrieve_failopen.py) um den positiven Pfad:
ist Ollama da, MUSS das Vektor-Bein einen echten semantischen Treffer liefern.
"""
from __future__ import annotations

import sys

import pytest


def _ollama_bereit() -> bool:
    """True, wenn Ollama erreichbar ist und ein Embedding liefert (bge-m3 gezogen)."""
    try:
        from markmem.core import vector_store as vs
        return vs.embed_one("ping", timeout=5) is not None
    except Exception:
        return False


@pytest.mark.ollama
def test_vector_store_echte_suche(markmem_env):
    if not _ollama_bereit():
        pytest.skip("Ollama/bge-m3 nicht erreichbar — Vektor-Test übersprungen")

    from markmem.core import embed_memories
    from markmem.core import vector_store as vs

    # Index im isolierten tmp-Korpus bauen (--rebuild).
    alt = sys.argv
    sys.argv = ["embed_memories", "--rebuild", "--quiet"]
    try:
        rc = embed_memories.main()
    finally:
        sys.argv = alt
    assert rc == 0

    # Semantische Suche mit umschreibendem Begriff (nicht die exakten Karten-Worte):
    # "veraltete zwischengespeicherte Einträge" sollte die Caching-Karte treffen.
    res = vs.search("veraltete zwischengespeicherte Einträge ungültig machen", k=5, timeout=10)
    assert res, "mit laufendem Ollama sollte die Suche Treffer liefern"
    files = [f for f, _ in res]
    assert any("caching" in f for f in files), f"erwartete Caching-Karte unter Treffern: {files}"


@pytest.mark.ollama
def test_retrieve_mit_vektor_bein(markmem_env):
    if not _ollama_bereit():
        pytest.skip("Ollama/bge-m3 nicht erreichbar — Vektor-Test übersprungen")

    from markmem.core import embed_memories
    from markmem.core import memory_retrieve as mr

    alt = sys.argv
    sys.argv = ["embed_memories", "--rebuild", "--quiet"]
    try:
        assert embed_memories.main() == 0
    finally:
        sys.argv = alt

    q = "wie halte ich zwischengespeicherte daten frisch"
    res = mr.retrieve(mr.tokenize(q), q.lower(), k=5, exclude=None, use_vectors=True)
    assert res
    # Mit Ollama MUSS mindestens ein Treffer einen Vektor-Rang haben.
    assert any(r.get("vector_rank") is not None for r in res), \
        "mit laufendem Ollama sollte das Vektor-Bein beitragen"
