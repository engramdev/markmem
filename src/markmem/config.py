"""
markmem.config — zentrale Auflösung von Pfaden, Modellen und domänenspezifischen
Einstellungen. Auflösungs-Reihenfolge je Wert: **Env-Variable > Profil-TOML > Default**.

Der Default zeigt auf den mitgelieferten `examples/`-Korpus, damit das Paket „out of
the box" läuft (Index/Retrieve/Dashboard auf synthetischen Demo-Daten). In Produktion
setzt man `MARKMEM_MEMORY_DIR` (und optional ein Profil) per Umgebungsvariable.

Profile (TOML unter examples/profiles/, gewählt via MARKMEM_PROFILE):
  - generic   (Default): domänenneutral
  - ein Beispiel-Profil (examples/profiles/) zeigt domänenspezifisches Override

Fail-open: fehlt etwas, greift der Default — nie ein harter Abbruch wegen Config.
"""
from __future__ import annotations

import os
from pathlib import Path

# Paket- und Repo-Wurzel (für den examples-Default)
_PKG = Path(__file__).resolve().parent              # …/src/markmem
_SRC = _PKG.parent                                  # …/src
_REPO = _SRC.parent                                 # Repo-Wurzel
EXAMPLES = _REPO / "examples"


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v else default


def _load_profil() -> dict:
    """Optionales Profil-TOML laden. Name oder Pfad via MARKMEM_PROFILE."""
    name = os.environ.get("MARKMEM_PROFILE", "").strip()
    if not name:
        return {}
    p = Path(name) if name.endswith(".toml") else EXAMPLES / "profiles" / f"{name}.toml"
    if not p.exists():
        return {}
    try:
        import tomllib
        with open(p, "rb") as fh:
            return tomllib.load(fh)
    except Exception:
        return {}


PROFIL = _load_profil()


def profil_wert(pfad: str, default):
    """Verschachtelten Profil-Wert per Punkt-Pfad holen (z.B. 'deadend.glob')."""
    knoten = PROFIL
    for teil in pfad.split("."):
        if not isinstance(knoten, dict) or teil not in knoten:
            return default
        knoten = knoten[teil]
    return knoten


# ── Kern-Pfade (Env > examples-Default) ────────────────────────────────────────
MEMORY_DIR = Path(_env("MARKMEM_MEMORY_DIR", str(EXAMPLES / "memory")))
GRAPH = Path(_env("MARKMEM_GRAPH", str(EXAMPLES / "graph" / "graph.json")))
OLLAMA_URL = _env("MARKMEM_OLLAMA_URL", "http://127.0.0.1:11434")

# ── Modelle ────────────────────────────────────────────────────────────────────
EMBED_MODEL = _env("MARKMEM_EMBED_MODEL", "bge-m3")
EMBED_DIM = int(_env("MARKMEM_EMBED_DIM", "1024"))
LLM_MODEL = _env("MARKMEM_LLM_MODEL", "dolphin-llama3:8b")
RERANK_MODEL = _env("MARKMEM_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

# ── Domänen-Einstellungen (Env > Profil > generischer Default) ──────────────────
# Dead-End/Negativ-Wissen-Katalog (generalisiert aus dem früheren "Nieten"-Harvest)
DEADEND_DIR = Path(_env("MARKMEM_DEADEND_DIR",
                        profil_wert("deadend.dir", str(EXAMPLES / "deadend_sources" / "nieten"))))
DEADEND_GLOB = _env("MARKMEM_DEADEND_GLOB", profil_wert("deadend.glob", "*/DEADEND.md"))
DEADEND_REGISTRY_NAME = profil_wert("deadend.registry_name", "reference_deadends_registry.md")

# Entity-Quelle für die Graph-Verdichtung: 'dir' | 'file' | 'list'
ENTITY_SOURCE = _env("MARKMEM_ENTITY_SOURCE", profil_wert("entity.source", "dir"))
ENTITY_DIR = Path(_env("MARKMEM_ENTITY_DIR", profil_wert("entity.dir", str(EXAMPLES / "memory"))))
ENTITY_FILE = _env("MARKMEM_ENTITY_FILE", profil_wert("entity.file", ""))
ENTITY_LIST = profil_wert("entity.list", [])
# Generische Stoppwörter, die nicht als Entity-Namensteil zählen
ENTITY_GENERIC = set(profil_wert("entity.generic",
                                 ["test", "demo", "example", "sample", "temp", "todo", "misc", "data"]))

# cwd→Kontext-Pattern für die Hook-Integration (Liste von [regex, tag])
CONTEXT_PATTERNS = profil_wert("context.patterns", [["/projects/([a-z0-9_-]+)", "project"]])


def info() -> dict:
    """Aufgelöste Konfiguration (für Status/Debug)."""
    return {
        "MEMORY_DIR": str(MEMORY_DIR), "GRAPH": str(GRAPH), "OLLAMA_URL": OLLAMA_URL,
        "EMBED_MODEL": EMBED_MODEL, "profile": os.environ.get("MARKMEM_PROFILE", "(none)"),
        "DEADEND_DIR": str(DEADEND_DIR), "ENTITY_SOURCE": ENTITY_SOURCE,
    }
