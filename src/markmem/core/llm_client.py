"""Observable client for the Ollama /api/generate endpoint.

Three call sites -- compaction, contradiction scan, and eval -- used to carry
byte-identical copies of this call, each failing silently (returning None on any
error with no trace). This is the single, shared, observable version: it keeps the
fail-open contract (returns None so the caller degrades gracefully) but logs the
classified failure reason -- never the prompt -- and counts it.

Mirrors the embedding path in vector_store.py; kept separate because that one speaks
/api/embed and this one /api/generate.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from markmem.config import LLM_MODEL, OLLAMA_URL
from markmem.logging import get_logger

log = get_logger(__name__)

_STATS: dict[str, int] = {
    "generate_http_error": 0,
    "generate_conn_error": 0,
    "generate_bad_response": 0,
}


def stats() -> dict[str, int]:
    """Snapshot of the generate-failure counters (observable fail-open)."""
    return dict(_STATS)


def generate(prompt: str, *, timeout: int = 90, temperature: float = 0.0,
             model: str | None = None) -> str | None:
    """One Ollama /api/generate call. Returns the response text, or None on any
    failure so the caller stays fail-open -- but the failure is logged (never with
    the prompt) and counted."""
    payload = json.dumps(
        {"model": model or LLM_MODEL, "prompt": prompt, "stream": False,
         "options": {"temperature": temperature}}
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()).get("response", "")
    except urllib.error.HTTPError as exc:  # subclass of URLError -- catch first
        _STATS["generate_http_error"] += 1
        log.warning("llm generate failed: HTTP %s (%s)", exc.code,
                    "transient" if exc.code >= 500 else "permanent")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _STATS["generate_conn_error"] += 1
        log.warning("llm generate failed: %s (is ollama up at %s?)",
                    type(exc).__name__, OLLAMA_URL)
        return None
    except json.JSONDecodeError:
        _STATS["generate_bad_response"] += 1
        log.warning("llm generate returned malformed JSON")
        return None
