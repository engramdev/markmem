"""Observable fail-open for the shared /api/generate client, plus proof that the
three rewired call sites still import and delegate to it.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from markmem.core import llm_client


def _reset_stats():
    for key in llm_client._STATS:
        llm_client._STATS[key] = 0


def test_http_5xx_is_fail_open_and_counted(monkeypatch):
    _reset_stats()

    def boom(*_a, **_k):
        raise urllib.error.HTTPError("http://x/api/generate", 502, "bad gateway", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert llm_client.generate("hello", timeout=5) is None
    assert llm_client.stats()["generate_http_error"] == 1


def test_connection_error_is_counted(monkeypatch):
    _reset_stats()

    def boom(*_a, **_k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert llm_client.generate("hello", timeout=5, temperature=0.4) is None
    assert llm_client.stats()["generate_conn_error"] == 1


def test_rewired_callers_import_and_delegate(monkeypatch):
    from markmem.core import contradiction_scan, memory_compact
    from markmem.eval import eval_retrieval

    monkeypatch.setattr(llm_client, "generate", lambda _p, **_kw: "answer")
    assert contradiction_scan.llm("q") == "answer"
    assert memory_compact.generate("q") == "answer"
    assert eval_retrieval.llm("q") == "answer"  # eval strips; "answer" is unchanged


def test_eval_caller_preserves_none_on_failure(monkeypatch):
    from markmem.eval import eval_retrieval

    monkeypatch.setattr(llm_client, "generate", lambda _p, **_kw: None)
    assert eval_retrieval.llm("q") is None  # .strip() must not blow up on None
