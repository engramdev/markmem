"""
tests/conftest.py — gemeinsames Test-Fundament für markmem.

Zwei Kern-Aufgaben, beide BEVOR irgendein markmem-Modul importiert wird:

  1. ``sys.path`` auf ``src`` sicherstellen (Tests laufen auch ohne installiertes
     Paket, z.B. ``PYTHONPATH=src`` oder ganz ohne — wir biegen es selbst gerade).
  2. ``MARKMEM_MEMORY_DIR`` / ``MARKMEM_GRAPH`` auf eine **temporäre Kopie** von
     ``examples/memory`` + ``examples/graph`` zeigen lassen, damit kein Test je den
     echten Demo-Korpus verändert (deadend_catalog/graph_densify/eval schreiben Dateien).

WICHTIG — Reihenfolge: ``markmem.config`` liest die Pfade EINMAL beim Import als
Modul-Konstanten (und ``markmem.paths`` leitet daraus ab). Die Env-Variablen müssen
also gesetzt sein, bevor das erste markmem-Modul geladen wird. Deshalb:
  * Der ``src``-Pfad + ein Default-Tmp-Korpus werden auf Modul-Ebene (Import-Zeit
    dieser conftest, also vor der Test-Sammlung) gesetzt.
  * Die Fixture ``markmem_env`` (autouse) gibt JEDEM Test eine FRISCHE Kopie und
    lädt ``config``/``paths`` per ``importlib.reload`` neu, sodass Tests sich nicht
    gegenseitig beeinflussen.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
from pathlib import Path

import pytest

# ── Pfade ───────────────────────────────────────────────────────────────────────
_TESTS_DIR = Path(__file__).resolve().parent
_REPO = _TESTS_DIR.parent
_SRC = _REPO / "src"
_EX_MEMORY = _REPO / "examples" / "memory"
_EX_GRAPH = _REPO / "examples" / "graph" / "graph.json"

# (1) src importierbar machen — robust, auch ohne installiertes Paket / ohne PYTHONPATH.
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _kopiere_korpus(ziel: Path) -> tuple[Path, Path]:
    """Lege unter ``ziel`` eine isolierte Kopie von memory/ + graph.json an.
    Gibt (memory_dir, graph_json) zurück."""
    mem = ziel / "memory"
    graph_dir = ziel / "graph"
    shutil.copytree(_EX_MEMORY, mem)
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph = graph_dir / "graph.json"
    if _EX_GRAPH.exists():
        shutil.copy2(_EX_GRAPH, graph)
    else:  # fail-open: leerer Graph, falls Beispiel fehlt
        graph.write_text("", encoding="utf-8")
    return mem, graph


def _reload_markmem() -> None:
    """config + paths (und alle bereits geladenen markmem-Submodule, die die Pfade
    als Modul-Konstanten cachen) neu laden, damit die frisch gesetzten Env-Variablen
    greifen. Reihenfolge: config zuerst (Quelle), dann paths (leitet ab), dann den Rest."""
    for name in ("markmem.config", "markmem.paths"):
        mod = sys.modules.get(name)
        if mod is not None:
            importlib.reload(mod)
    # Module, die config/paths-Werte beim Import als eigene Modul-Konstanten kopieren,
    # ebenfalls neu laden (sonst zeigen MEM/GRAPH/OUT/DEADEND_DIR noch auf alt).
    for name in list(sys.modules):
        if name.startswith("markmem.") and name not in ("markmem.config", "markmem.paths"):
            mod = sys.modules.get(name)
            if mod is not None:
                try:
                    importlib.reload(mod)
                except Exception:
                    pass


# (2) Direkt bei conftest-Import einen Default-Tmp-Korpus setzen, damit schon der
#     allererste markmem-Import (vor jeder Fixture) NIE auf das echte examples/ zeigt.
_BOOT = Path(os.environ.get("PYTEST_TMP_BOOT", "")) if os.environ.get("PYTEST_TMP_BOOT") else None
if _BOOT is None:
    import tempfile
    _BOOT = Path(tempfile.mkdtemp(prefix="markmem-boot-"))
    _bm, _bg = _kopiere_korpus(_BOOT)
    os.environ.setdefault("MARKMEM_MEMORY_DIR", str(_bm))
    os.environ.setdefault("MARKMEM_GRAPH", str(_bg))

# Dashboard-Tests deterministisch + nicht-interaktiv halten.
os.environ.setdefault("MEMDASH_INTRO", "aus")


@pytest.fixture
def markmem_env(tmp_path, monkeypatch):
    """Frische, isolierte Korpus-Kopie + neu geladene markmem-Module pro Test.

    Liefert ein kleines Objekt mit ``memory_dir`` / ``graph`` (Path), damit Tests
    direkt darauf zugreifen können. Setzt die Env via ``monkeypatch`` (auto-zurück).
    """
    mem, graph = _kopiere_korpus(tmp_path / "korpus")
    monkeypatch.setenv("MARKMEM_MEMORY_DIR", str(mem))
    monkeypatch.setenv("MARKMEM_GRAPH", str(graph))
    monkeypatch.setenv("MEMDASH_INTRO", "aus")
    _reload_markmem()

    class _Env:
        memory_dir = mem
        graph_json = graph

    yield _Env()


@pytest.fixture(autouse=True)
def _isoliere_env(markmem_env):
    """Autouse: jeder Test bekommt automatisch die isolierte Umgebung — kein Test
    fasst je den echten examples-Korpus an."""
    return markmem_env
