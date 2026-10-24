"""Structured, privacy-aware logging for markmem.

Design goals (see THREAT_MODEL.md):
  * **Zero hard dependency.** Pure stdlib ``logging``. structlog and OpenTelemetry
    are used only if importable — never required.
  * **Never log memory text or secrets.** Library code logs IDs, counts, latencies
    and hashes, not card content. A redaction backstop masks bearer tokens and
    ``key=value`` secrets, and neutralises CR/LF log injection, in case something
    slips into an error string.
  * **Library vs application split.** Modules call :func:`get_logger` and attach no
    handler (a ``NullHandler`` on the ``markmem`` root keeps the "no handlers"
    warning away). The *application entry point* calls :func:`configure` once to
    decide format and level.

Each record carries an operation id (``op_id``, a contextvar) and, when
OpenTelemetry is active, the current ``trace_id`` — so logs correlate across a run
and with traces.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import time
import uuid

_ROOT = "markmem"
_OP_ID: contextvars.ContextVar[str] = contextvars.ContextVar("markmem_op_id", default="")

# Values for these keys must never appear in a log line.
_DENY_KEYS = ("authorization", "api_key", "apikey", "token", "password", "secret", "content")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)\S+")
_KV_RE = re.compile(r"(?i)(" + "|".join(_DENY_KEYS) + r")(\s*[=:]\s*)(\S+)")


def _scrub(text: str) -> str:
    """Redaction backstop: neutralise CR/LF and mask obvious secrets."""
    if not text:
        return text
    text = text.replace("\r", "\\r").replace("\n", "\\n")  # CR/LF log-injection (OWASP)
    text = _BEARER_RE.sub(r"\1***", text)
    text = _KV_RE.sub(r"\1\2***", text)
    return text


# --------------------------------------------------------------- op id --------
def new_op(op_id: str | None = None) -> str:
    """Start a new logical operation; every log line in this context carries it.

    Call at the top of a CLI command / hook invocation. Returns the id so a caller
    can echo it. Uses a short random id when none is given.
    """
    oid = op_id or uuid.uuid4().hex[:12]
    _OP_ID.set(oid)
    return oid


def current_op() -> str:
    return _OP_ID.get("")


def _trace_id() -> str:
    """Current OpenTelemetry trace id, or '' if OTel is absent/inactive (soft import)."""
    try:
        from opentelemetry import trace  # type: ignore

        ctx = trace.get_current_span().get_span_context()
    except Exception:  # noqa: BLE001 - OTel is optional; a trace lookup must never break logging
        return ""
    if ctx and getattr(ctx, "trace_id", 0):
        return format(ctx.trace_id, "032x")
    return ""


# --------------------------------------------------------------- filters ------
class _ContextFilter(logging.Filter):
    """Attach op_id + trace_id to every record so formatters can emit them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.op_id = _OP_ID.get("")
        record.trace_id = _trace_id()
        return True


# ------------------------------------------------------------- formatters -----
class _JsonFormatter(logging.Formatter):
    """One JSON object per line. Scrubs the final message and the exception text."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "event": _scrub(record.getMessage()),
            "op_id": getattr(record, "op_id", ""),
        }
        tid = getattr(record, "trace_id", "")
        if tid:
            payload["trace_id"] = tid
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                payload.setdefault(k, v)
        if record.exc_info and record.exc_info[0] is not None:
            payload["error.type"] = record.exc_info[0].__name__
            payload["error.message"] = _scrub(str(record.exc_info[1]))
        return json.dumps(payload, ensure_ascii=False)


class _ScrubTextFormatter(logging.Formatter):
    """Human-readable line; scrubs the fully-rendered message (message + args)."""

    def format(self, record: logging.LogRecord) -> str:
        return _scrub(super().format(record))


# --------------------------------------------------------------- api ----------
def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger for library code. Attaches no handler of its own.

    Pass ``__name__`` from inside the package (already ``markmem.…``). A
    ``NullHandler`` on the root keeps the stdlib "no handlers found" warning away
    until the application calls :func:`configure`.
    """
    root = logging.getLogger(_ROOT)
    if not any(isinstance(h, logging.NullHandler) for h in root.handlers):
        root.addHandler(logging.NullHandler())
    if not name.startswith(_ROOT):
        name = f"{_ROOT}.{name}"
    return logging.getLogger(name)


def configure(level: str | None = None, fmt: str | None = None, stream=None) -> logging.Logger:
    """Configure the ``markmem`` logger for an application run. Idempotent.

    level: ``MARKMEM_LOG_LEVEL`` env or WARNING. fmt: ``MARKMEM_LOG_FORMAT`` env,
    ``json`` (default) or ``text``. Only markmem's own handlers are replaced, so a
    host application's logging config is left untouched.
    """
    level = (level or os.getenv("MARKMEM_LOG_LEVEL", "WARNING")).upper()
    fmt = (fmt or os.getenv("MARKMEM_LOG_FORMAT", "json")).lower()
    root = logging.getLogger(_ROOT)
    root.setLevel(getattr(logging, level, logging.WARNING))
    for h in [h for h in root.handlers if getattr(h, "_markmem", False)]:
        root.removeHandler(h)
    handler: logging.Handler = logging.StreamHandler(stream or sys.stderr)
    handler._markmem = True  # type: ignore[attr-defined]
    handler.addFilter(_ContextFilter())
    if fmt == "text":
        handler.setFormatter(
            _ScrubTextFormatter("%(asctime)s %(levelname)s %(name)s [op=%(op_id)s] %(message)s")
        )
    else:
        handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.propagate = False  # don't double-log through the Python root logger
    return root
