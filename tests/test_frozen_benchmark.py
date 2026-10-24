"""
tests/test_frozen_benchmark.py — der reproduzierbare, deterministische Frozen-Benchmark.

Der Frozen-Benchmark rechnet über den EINGEFRORENEN Gold-Set (examples/eval/goldset.json)
feste Qualitätszahlen (recall@1/3/5 + mrr + Bootstrap-CI) über den synthetischen
Demo-Korpus — ohne LLM/Ollama. Dieser Test sichert die drei Versprechen ab:

  (a) DETERMINISMUS — zwei Läufe der Scoring-/CI-Funktionen liefern bit-genau dieselben
      Metriken UND dieselben CI-Grenzen (fixer Bootstrap-Seed, kein Random ohne Seed).
  (b) ANTWORTBARKEIT — BM25+Entity (Ollama-frei) räumt bei recall@3 eine vernünftige
      Untergrenze (>= 0.5); beweist, dass der Gold-Set fair beantwortbar ist und die
      Pipeline wirklich misst (statt nur Nullen zu schreiben).
  (c) INTEGRITÄT — jeder ``gold``-Dateiname im Gold-Set existiert als Karte im Korpus.

Läuft über die autouse-Fixture ``markmem_env`` (isolierte Korpus-Kopie), ruft die
Eval-Funktionen programmatisch auf (kein Shell-Out).
"""
from __future__ import annotations

import json
from pathlib import Path

# Gold-Set liegt im Repo (nicht im tmp-Korpus) — fester Pfad relativ zu diesem Test.
_REPO = Path(__file__).resolve().parent.parent
GOLDSET = _REPO / "examples" / "eval" / "goldset.json"


def test_goldset_gold_dateien_existieren(markmem_env):
    """(c) Jeder gold-Dateiname muss als Karte im (kopierten) Korpus liegen."""
    pairs = json.loads(GOLDSET.read_text(encoding="utf-8"))
    assert pairs, "Gold-Set ist leer"
    for d in pairs:
        gold = d["gold"]
        assert (markmem_env.memory_dir / gold).exists(), f"Gold-Karte fehlt im Korpus: {gold}"
        assert gold.endswith(".sample.md"), f"Gold muss eine Sample-Karte sein: {gold}"


def test_frozen_deterministisch(markmem_env):
    """(a) Zwei Läufe liefern identische Metriken UND identische CI-Grenzen."""
    from markmem.eval import eval_retrieval as ev

    r1 = ev.run_frozen(GOLDSET, k=10, use_vectors=False)
    r2 = ev.run_frozen(GOLDSET, k=10, use_vectors=False)

    assert r1["ranks"] == r2["ranks"]
    assert r1["metrics"] == r2["metrics"]
    assert r1["ci95"] == r2["ci95"], "Bootstrap-CI muss bei fixem Seed reproduzierbar sein"

    # Bootstrap selbst ist bei fixem Seed deterministisch (unabhängig vom Retrieval).
    ranks = [1, 2, None, 1, 3, None, 1, 5, 2, 1]
    assert ev.bootstrap_cis(ranks) == ev.bootstrap_cis(ranks)


def test_frozen_recall_floor(markmem_env):
    """(b) BM25+Entity (Ollama-frei) klärt den Antwortbarkeits-Floor recall@3 >= 0.5."""
    from markmem.eval import eval_retrieval as ev

    result = ev.run_frozen(GOLDSET, k=10, use_vectors=False)
    assert result["use_vectors"] is False  # Ollama-frei
    assert result["n"] >= 1

    m = result["metrics"]
    assert m["recall@3"] >= 0.5, f"Gold-Set sollte über BM25 beantwortbar sein, recall@3={m['recall@3']}"

    # CI-Grenzen sind sauber: lo <= Punktwert <= hi, alles in [0, 1].
    for kx in ("recall@1", "recall@3", "recall@5", "mrr"):
        lo, hi = result["ci95"][kx]
        assert 0.0 <= lo <= m[kx] <= hi <= 1.0, f"CI-Grenzen unplausibel für {kx}: {lo} <= {m[kx]} <= {hi}"


def test_frozen_main_schreibt_metriken(markmem_env, monkeypatch):
    """main(--goldset) läuft Ollama-frei durch und schreibt die Frozen-Metrik-JSON."""
    import sys

    from markmem.eval import eval_retrieval as ev

    monkeypatch.setattr(sys, "argv", ["eval_retrieval", "--goldset", str(GOLDSET), "--k", "10"])
    assert ev.main() == 0

    assert ev.FROZEN_OUT.exists(), f"erwartete Frozen-Metrik-Datei {ev.FROZEN_OUT}"
    data = json.loads(ev.FROZEN_OUT.read_text(encoding="utf-8"))
    assert data["use_vectors"] is False
    for key in ("recall@1", "recall@3", "recall@5", "mrr"):
        assert key in data["metrics"]
        assert key in data["ci95"]
