"""
markmem.paths — abgeleitete Unterpfade. Eine Quelle der Wahrheit für alle Sub-Pfade,
damit kein Modul mehr Pfade selbst zusammensetzt. Alles relativ zu config.MEMORY_DIR.
"""
from __future__ import annotations

from markmem import config

MEMORY_DIR = config.MEMORY_DIR
GRAPH = config.GRAPH

METRICS = MEMORY_DIR / "metrics"
INBOX = MEMORY_DIR / "inbox"

VECTOR_INDEX = METRICS / "vector_index.sqlite"
INDEX_CACHE = METRICS / "memory_index.json"
KALIB_FILE = METRICS / "kalibrierung.json"
EVAL_JSON = METRICS / "eval_retrieval.json"
EVAL_GOLDSET = METRICS / "eval_goldset.json"
HEALTH = METRICS / "memory_health.json"
CONFIDENCE_HISTORY = METRICS / "confidence_history.jsonl"
ACCESS_LOG = METRICS / "access_log.jsonl"

RETRIEVAL_CONFIG = MEMORY_DIR / "retrieval_config.json"
RULES_FILE = MEMORY_DIR / "MEMORY_RULES.md"
INDEX_FILE = MEMORY_DIR / "MEMORY.md"
DEEP_FILE = MEMORY_DIR / "MEMORY_DEEP.md"
INFRA_FILE = MEMORY_DIR / "MEMORY_INFRA.md"
DEADEND_REGISTRY = MEMORY_DIR / config.DEADEND_REGISTRY_NAME

# Dateien, die kein atomares Wissen sind (nicht embedden, nicht als Treffer)
SKIP_FILES = {"MEMORY.md", "MEMORY_DEEP.md", "MEMORY_INFRA.md", "MEMORY_RULES.md"}
