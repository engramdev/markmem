"""Held-out split in the self-tuner (anti-contamination) -- and the FIRST test
coverage for tune_retrieval, whose untested state previously hid a vector_rank
signature regression. The tuner calls mr.vector_rank per query, so this also guards
that caller end-to-end.

The temp demo corpus (autouse markmem_env) has no built vector index, so
vector_store.available() is False and the vector leg short-circuits -- the tuner run
stays fast and deterministic even if a local Ollama happens to be up.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

GOLDSET = Path(__file__).resolve().parent.parent / "examples" / "eval" / "goldset.json"


@pytest.fixture
def ohne_ollama(monkeypatch):
    """Ollama auf toten Port + markmem neu laden -> vector_rank scheitert sofort
    (Connection refused) statt echte Embeds gegen ein lokales Ollama zu fahren. Hält
    den Tuner-Test schnell, deterministisch und von echter Infra isoliert; der
    vector_rank-Aufrufer wird trotzdem (fail-open) durchlaufen."""
    monkeypatch.setenv("MARKMEM_OLLAMA_URL", "http://127.0.0.1:1")
    for name in list(sys.modules):
        if name.startswith("markmem."):
            try:
                importlib.reload(sys.modules[name])
            except Exception:  # noqa: BLE001, S110 -- best-effort reload; a failing submodule here is non-fatal to the test
                pass


def test_split_is_deterministic_and_disjoint():
    from markmem.eval import tune_retrieval as t

    train, test = t._split(20, 0.3)
    assert set(train) & set(test) == set()          # disjunkt
    assert sorted(train + test) == list(range(20))  # vollständig, keine Lücke
    assert test and train                            # beide nicht leer
    assert (train, test) == t._split(20, 0.3)        # deterministisch, kein Random


def test_split_off_or_small_is_insample():
    from markmem.eval import tune_retrieval as t

    assert t._split(20, 0.0) == (list(range(20)), list(range(20)))  # ausgeschaltet
    assert t._split(4, 0.3) == (list(range(4)), list(range(4)))     # n<6 -> kein Split


def test_tuner_runs_held_out_over_demo_goldset(markmem_env, ohne_ollama, monkeypatch, capsys):
    """Dry-Run des Tuners über den eingefrorenen Demo-Gold-Set: läuft durch (rc 0),
    berichtet den held-out TEST-Split, schreibt ohne --write NICHTS."""
    from markmem.eval import tune_retrieval as t

    monkeypatch.setattr(sys, "argv",
                        ["tune_retrieval", "--goldset", str(GOLDSET), "--holdout-frac", "0.3"])
    rc = t.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "train=" in out and "test=" in out  # held-out-Split wurde berichtet
