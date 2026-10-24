"""Observable fail-open for the embedding path.

The contract: an embedding failure must NOT raise (retrieval falls back to BM25+entity),
but it must no longer be silent -- each failure class increments a counter.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from markmem.core import vector_store as vs


def _reset_stats():
    for key in vs._STATS:
        vs._STATS[key] = 0


def test_http_5xx_is_fail_open_and_counted(monkeypatch):
    _reset_stats()

    def boom(*_a, **_k):
        raise urllib.error.HTTPError("http://x/api/embed", 503, "busy", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert vs._embed_call(["hello"], "bge-m3", 5) is None  # fail-open preserved
    assert vs.stats()["embed_http_error"] == 1  # but observable


def test_http_4xx_is_counted(monkeypatch):
    _reset_stats()

    def boom(*_a, **_k):
        raise urllib.error.HTTPError("http://x/api/embed", 400, "bad request", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert vs._embed_call(["hello"], "bge-m3", 5) is None
    assert vs.stats()["embed_http_error"] == 1


def test_connection_error_is_counted(monkeypatch):
    _reset_stats()

    def boom(*_a, **_k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert vs._embed_call(["hello"], "bge-m3", 5) is None
    assert vs.stats()["embed_conn_error"] == 1


def test_stats_returns_a_copy():
    before = vs.stats()["embed_http_error"]
    snapshot = vs.stats()
    snapshot["embed_http_error"] = before + 999
    assert vs.stats()["embed_http_error"] == before  # internal counters untouched
