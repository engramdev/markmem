"""Tests for the P2 observability foundation: errors.py + logging.py.

These cover the two promises that matter for an auditable tool: (1) the error
hierarchy lets a caller distinguish retryable from permanent without catching bare
Exception, and (2) logging never emits a secret and is parseable JSON with an
operation id for correlation.
"""
from __future__ import annotations

import io
import json
import logging as _stdlib_logging

from markmem import errors
from markmem import logging as mlog


# --------------------------------------------------------------- errors -------
def test_error_hierarchy():
    assert issubclass(errors.ConfigError, errors.MarkmemError)
    assert issubclass(errors.StorageError, errors.MarkmemError)
    assert issubclass(errors.RetrievalError, errors.MarkmemError)
    assert issubclass(errors.ProviderError, errors.MarkmemError)
    # the retry-relevant split
    assert issubclass(errors.TransientProviderError, errors.ProviderError)
    assert issubclass(errors.PermanentProviderError, errors.ProviderError)
    # a caller can isolate "our" errors from genuine bugs
    assert isinstance(errors.TransientProviderError("x"), errors.MarkmemError)
    assert not isinstance(ValueError("x"), errors.MarkmemError)


# --------------------------------------------------------------- scrub --------
def test_scrub_masks_bearer_token():
    assert "sk-secret-123" not in mlog._scrub("Authorization: Bearer sk-secret-123")


def test_scrub_masks_keyed_secrets():
    for raw in ("api_key=ABC123", "token: deadbeef", "password=hunter2", "secret = xyz"):
        out = mlog._scrub(raw)
        assert "***" in out
        assert raw.split("=")[-1].split(":")[-1].strip() not in out


def test_scrub_neutralises_crlf_injection():
    out = mlog._scrub("line1\r\nFAKE LOG ENTRY level=CRITICAL")
    assert "\n" not in out and "\r" not in out
    assert "\\r\\n" in out


# --------------------------------------------------------------- json ---------
def _capture(fmt="json", level="INFO"):
    buf = io.StringIO()
    mlog.configure(level=level, fmt=fmt, stream=buf)
    return buf


def test_json_log_is_parseable_with_fields():
    buf = _capture()
    log = mlog.get_logger("markmem.test")
    log.warning("embed degraded, falling back to bm25")
    line = buf.getvalue().strip().splitlines()[-1]
    obj = json.loads(line)
    assert obj["level"] == "WARNING"
    assert obj["logger"] == "markmem.test"
    assert obj["event"] == "embed degraded, falling back to bm25"
    assert "ts" in obj and "op_id" in obj


def test_op_id_is_attached_and_stable():
    buf = _capture()
    oid = mlog.new_op("op-abc123")
    assert oid == "op-abc123"
    mlog.get_logger("markmem.test").error("boom")
    obj = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert obj["op_id"] == "op-abc123"


def test_json_log_never_leaks_a_secret():
    buf = _capture()
    mlog.get_logger("markmem.test").warning("provider call failed with api_key=TOPSECRET42")
    out = buf.getvalue()
    assert "TOPSECRET42" not in out
    assert "***" in out


def test_configure_is_idempotent_single_handler():
    buf = io.StringIO()
    mlog.configure(fmt="json", stream=buf)
    mlog.configure(fmt="json", stream=buf)
    root = _stdlib_logging.getLogger("markmem")
    markmem_handlers = [h for h in root.handlers if getattr(h, "_markmem", False)]
    assert len(markmem_handlers) == 1


def test_get_logger_namespaces_and_adds_nullhandler():
    log = mlog.get_logger("sub.module")  # no markmem prefix
    assert log.name == "markmem.sub.module"
    root = _stdlib_logging.getLogger("markmem")
    assert any(isinstance(h, _stdlib_logging.NullHandler) for h in root.handlers)
