"""
tests/test_config.py — Auflösungs-Logik der zentralen Config.

Geprüft:
  * Env-Override schlägt den eingebauten Default (MARKMEM_MEMORY_DIR).
  * Ohne Env → examples-Default (MEMORY_DIR zeigt unter examples/memory).
  * Profil-Auflösung: MARKMEM_PROFILE=bugbounty lädt die Profil-Werte
    (deadend.glob/registry_name) statt der generischen Defaults.

Da config die Werte beim Import als Modul-Konstanten festlegt, wird hier nach jedem
Env-Wechsel gezielt ``importlib.reload`` ausgeführt.
"""
from __future__ import annotations

import importlib
from pathlib import Path


def _reload_config(monkeypatch=None):
    import markmem.config as cfg
    return importlib.reload(cfg)


def test_env_override_schlaegt_default(tmp_path, monkeypatch):
    ziel = tmp_path / "mein_memory"
    ziel.mkdir()
    monkeypatch.setenv("MARKMEM_MEMORY_DIR", str(ziel))
    cfg = _reload_config()
    assert cfg.MEMORY_DIR == Path(str(ziel))


def test_ohne_env_examples_default(monkeypatch):
    # Env entfernen → eingebauter examples-Default muss greifen.
    monkeypatch.delenv("MARKMEM_MEMORY_DIR", raising=False)
    monkeypatch.delenv("MARKMEM_GRAPH", raising=False)
    cfg = _reload_config()
    assert cfg.MEMORY_DIR == cfg.EXAMPLES / "memory"
    assert cfg.GRAPH == cfg.EXAMPLES / "graph" / "graph.json"
    assert cfg.MEMORY_DIR.exists(), "examples/memory sollte mitgeliefert sein"


def test_graph_env_override(tmp_path, monkeypatch):
    g = tmp_path / "g.json"
    g.write_text("", encoding="utf-8")
    monkeypatch.setenv("MARKMEM_GRAPH", str(g))
    cfg = _reload_config()
    assert cfg.GRAPH == Path(str(g))


def test_profil_bugbounty_wird_geladen(monkeypatch):
    """MARKMEM_PROFILE=bugbounty → lädt die Werte aus dem bugbounty-Beispielprofil."""
    monkeypatch.setenv("MARKMEM_PROFILE", "bugbounty")
    # sicherstellen, dass kein Env-Override die Profil-Werte verdeckt
    monkeypatch.delenv("MARKMEM_DEADEND_GLOB", raising=False)
    cfg = _reload_config()
    # Werte aus bugbounty.toml:
    assert cfg.profil_wert("deadend.glob", None) == "*/NIETE.md"
    assert cfg.DEADEND_GLOB == "*/NIETE.md"
    assert cfg.DEADEND_REGISTRY_NAME == "reference_sackgassen_registry.md"
    assert cfg.info()["profile"] == "bugbounty"


def test_profil_generic_default_glob(monkeypatch):
    """Ohne Profil → generischer Default-Glob (*/DEADEND.md)."""
    monkeypatch.delenv("MARKMEM_PROFILE", raising=False)
    monkeypatch.delenv("MARKMEM_DEADEND_GLOB", raising=False)
    cfg = _reload_config()
    assert cfg.DEADEND_GLOB == "*/DEADEND.md"


def test_env_schlaegt_profil(monkeypatch):
    """Auflösungs-Reihenfolge Env > Profil: Env-Glob gewinnt gegen bugbounty-Profil."""
    monkeypatch.setenv("MARKMEM_PROFILE", "bugbounty")
    monkeypatch.setenv("MARKMEM_DEADEND_GLOB", "*/EIGEN.md")
    cfg = _reload_config()
    assert cfg.DEADEND_GLOB == "*/EIGEN.md"
