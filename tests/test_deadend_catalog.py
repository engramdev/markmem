"""
tests/test_deadend_catalog.py — Dead-End-Register-Erzeugung.

Über ``examples/deadend_sources`` (Demo: ``nieten/demo_widget/DEADEND.md``) erzeugt
``deadend_catalog`` ein Register-Markdown mit den erwarteten Sektionen
(Verdikt → „Tot weil", Re-Approach, Lehre). Glob + Output sind über Env konfigurierbar.

Der Schreib-Pfad ist ``paths.DEADEND_REGISTRY`` (im isolierten tmp-Korpus) — der echte
examples-Korpus wird nie berührt.
"""
from __future__ import annotations

import importlib
import sys

import pytest

_REPO_DEADEND = None  # wird im Fixture gefüllt


@pytest.fixture
def deadend_env(monkeypatch):
    """DEADEND_DIR auf den realen examples-Quellbaum zeigen (read-only), Output in den
    isolierten Korpus. Danach markmem-Module neu laden, damit die Konstanten greifen."""
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    quelle = repo / "examples" / "deadend_sources" / "nieten"
    monkeypatch.setenv("MARKMEM_DEADEND_DIR", str(quelle))
    monkeypatch.setenv("MARKMEM_DEADEND_GLOB", "*/DEADEND.md")
    for name in list(sys.modules):
        if name.startswith("markmem."):
            try:
                importlib.reload(sys.modules[name])
            except Exception:
                pass
    return quelle


def _run_catalog():
    # main() ruft argparse.parse_args() → muss ein sauberes argv sehen (nicht pytest-argv).
    from markmem.learn import deadend_catalog as dc
    alt = sys.argv
    sys.argv = ["deadend_catalog"]
    try:
        return dc.main()
    finally:
        sys.argv = alt


def test_register_wird_erzeugt_mit_sektionen(deadend_env):
    from markmem import paths

    rc = _run_catalog()
    assert rc == 0
    out = paths.DEADEND_REGISTRY
    assert out.exists(), f"Register {out} sollte geschrieben sein"
    txt = out.read_text(encoding="utf-8")

    # Frontmatter + Titel
    assert "name: reference-deadends-registry" in txt
    assert "Dead-End-Register" in txt
    # Demo-Entity als Sektion
    assert "## demo_widget — Dead-End" in txt
    # Geerntete Inhalte aus der DEADEND.md
    assert "**Tot weil:**" in txt        # aus Verdikt-Sektion
    assert "**Re-Approach nur wenn:**" in txt
    assert "**Lehre:**" in txt
    # Plattform-Zeile wurde erkannt
    assert "Plattform" in txt


def test_output_pfad_folgt_registry_name_env_profil(monkeypatch):
    """Der Registry-Dateiname kommt aus config (Default reference_deadends_registry.md).
    Mit Profil bugbounty heißt er anders → Output-Pfad folgt."""
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    quelle = repo / "examples" / "deadend_sources" / "nieten"
    monkeypatch.setenv("MARKMEM_DEADEND_DIR", str(quelle))
    monkeypatch.setenv("MARKMEM_PROFILE", "bugbounty")  # registry_name = reference_sackgassen_registry.md
    monkeypatch.delenv("MARKMEM_DEADEND_GLOB", raising=False)  # Profil-Glob */NIETE.md
    for name in list(sys.modules):
        if name.startswith("markmem."):
            try:
                importlib.reload(sys.modules[name])
            except Exception:
                pass

    from markmem import paths, config
    assert config.DEADEND_REGISTRY_NAME == "reference_sackgassen_registry.md"
    assert paths.DEADEND_REGISTRY.name == "reference_sackgassen_registry.md"
    # Profil-Glob */NIETE.md findet die Demo-DEADEND.md NICHT → "keine DEADEND" (rc 0, kein Register).
    rc = _run_catalog()
    assert rc == 0


def test_glob_treffer_leer_ist_kein_crash(monkeypatch):
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    quelle = repo / "examples" / "deadend_sources" / "nieten"
    monkeypatch.setenv("MARKMEM_DEADEND_DIR", str(quelle))
    monkeypatch.setenv("MARKMEM_DEADEND_GLOB", "*/GIBTESNICHT.md")
    for name in list(sys.modules):
        if name.startswith("markmem."):
            try:
                importlib.reload(sys.modules[name])
            except Exception:
                pass
    rc = _run_catalog()
    assert rc == 0  # leeres Ergebnis ist sauber, kein Fehler
