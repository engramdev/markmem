"""
adapters.py — Claude-Code-Hook-Adapter.

Eine einzige Stelle für die Claude-Code-Hook-Eingabeform: ein Hook bekommt sein
Event als JSON auf stdin (z.B. `{"cwd": "...", "transcript_path": "...",
"session_id": "..."}`). Andere Integrationen (CI, Cron, andere IDEs) liefern das
Event anders — die kapselt man dann in einem eigenen Adapter, ohne die portierten
Hook-Skripte anzufassen.

Fail-open: leeres/kaputtes stdin → {} (nie ein harter Abbruch).
"""
from __future__ import annotations

import json
import sys


def read_hook_event() -> dict:
    """Liest das Claude-Code-Hook-Event von stdin und gibt es als dict zurück.

    Leeres stdin oder ungültiges JSON ergibt {} (fail-open — der Hook soll eine
    Session nie blockieren)."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
