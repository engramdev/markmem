"""
tests/test_graph_densify.py — die drei Entity-Backends der Graph-Verdichtung.

``canonical_entities()`` zieht kanonische Entity-Namen aus einer pluggbaren Quelle:
  * ``dir``  — Verzeichnisnamen unter ENTITY_DIR
  * ``file`` — eine Entität pro Zeile aus ENTITY_FILE
  * ``list`` — statische Liste aus dem Profil (ENTITY_LIST)

Geprüft: jedes Backend liefert die erwarteten Knoten, und der ``ENTITY_GENERIC``-Filter
greift (Namen, deren ALLE signifikanten Teile generisch sind, werden verworfen; ebenso
Namen < 4 Zeichen). Da ``canonical_entities`` die config-Werte zur Laufzeit liest,
genügt monkeypatch auf das config-Modul (+ reload, damit das Modul-Konstanten-GENERIC frisch ist).
"""
from __future__ import annotations

import importlib
import sys

import pytest


def _reload_with_source(monkeypatch, source: str):
    """config + graph_densify so neu laden, dass ENTITY_SOURCE=source greift und
    das GENERIC-Set frisch ist. Gibt das graph_densify-Modul zurück."""
    monkeypatch.setenv("MARKMEM_ENTITY_SOURCE", source)
    monkeypatch.delenv("MARKMEM_PROFILE", raising=False)
    for name in ("markmem.config", "markmem.paths", "markmem.learn.graph_densify"):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    from markmem.learn import graph_densify
    return importlib.reload(graph_densify)


def test_backend_dir(monkeypatch, tmp_path):
    # Kontrollierte Entity-Verzeichnisse anlegen.
    base = tmp_path / "entdir"
    for name in ("widget-api", "deploy-pipeline", "ab", "test-demo", ".hidden", "_archive"):
        (base / name).mkdir(parents=True)
    monkeypatch.setenv("MARKMEM_ENTITY_DIR", str(base))

    gd = _reload_with_source(monkeypatch, "dir")
    ents = gd.canonical_entities()

    assert "widget-api" in ents
    assert "deploy-pipeline" in ents
    # < 4 Zeichen verworfen
    assert "ab" not in ents
    # rein generisch (test + demo beide in GENERIC) verworfen
    assert "test-demo" not in ents
    # versteckte / Utility-Dirs ignoriert
    assert ".hidden" not in ents
    assert "_archive" not in ents


def test_backend_file(monkeypatch, tmp_path):
    f = tmp_path / "entities.txt"
    f.write_text("widget-api\ndeploy-pipeline\n\nsample-data\nrate-limit\n", encoding="utf-8")
    monkeypatch.setenv("MARKMEM_ENTITY_FILE", str(f))

    gd = _reload_with_source(monkeypatch, "file")
    ents = gd.canonical_entities()

    assert "widget-api" in ents
    assert "deploy-pipeline" in ents
    assert "rate-limit" in ents
    # 'sample' + 'data' beide generisch → verworfen
    assert "sample-data" not in ents


def test_backend_list_via_profil(monkeypatch):
    """Das list-Backend liest config.ENTITY_LIST (aus dem Profil). Wir setzen die
    Liste direkt auf dem reloadeten config-Modul (simuliert Profil-Wert)."""
    monkeypatch.setenv("MARKMEM_ENTITY_SOURCE", "list")
    monkeypatch.delenv("MARKMEM_PROFILE", raising=False)
    import markmem.config as cfg
    importlib.reload(cfg)
    # Profil-Wert simulieren
    monkeypatch.setattr(cfg, "ENTITY_LIST", ["widget-api", "caching", "misc-temp", "xy"])
    import markmem.learn.graph_densify as gd
    importlib.reload(gd)

    ents = gd.canonical_entities()
    assert "widget-api" in ents
    assert "caching" in ents
    # 'misc' + 'temp' generisch → raus; 'xy' < 4 → raus
    assert "misc-temp" not in ents
    assert "xy" not in ents


def test_generic_filter_greift(monkeypatch, tmp_path):
    """Expliziter Nachweis des ENTITY_GENERIC-Filters über ein eigenes generic-Set."""
    f = tmp_path / "e.txt"
    f.write_text("foobar-baz\ntest-thing\n", encoding="utf-8")
    monkeypatch.setenv("MARKMEM_ENTITY_FILE", str(f))
    monkeypatch.setenv("MARKMEM_ENTITY_SOURCE", "file")
    import markmem.config as cfg
    importlib.reload(cfg)
    # 'thing' zusätzlich als generisch markieren → 'test-thing' (test+thing) fällt raus
    monkeypatch.setattr(cfg, "ENTITY_GENERIC", {"test", "thing"})
    import markmem.learn.graph_densify as gd
    importlib.reload(gd)
    # graph_densify.GENERIC ist beim reload aus config kopiert → erneut angleichen
    monkeypatch.setattr(gd, "GENERIC", {"test", "thing"})

    ents = gd.canonical_entities()
    assert "foobar-baz" in ents
    assert "test-thing" not in ents


def test_mentions_helper(monkeypatch):
    gd = _reload_with_source(monkeypatch, "dir")
    assert gd.mentions("the widget-api handles widgets", "widget-api")
    assert gd.mentions("deploy pipeline runs", "deploy-pipeline")
    assert not gd.mentions("nothing relevant here", "widget-api")
