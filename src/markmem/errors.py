"""Exception hierarchy for markmem.

markmem is fail-open on retrieval and fail-closed on risky writes. These types let
callers distinguish *what* failed and *whether a retry could help* — without
catching bare ``Exception`` and without swallowing errors silently.

All markmem-raised errors derive from :class:`MarkmemError`, so an application can
``except MarkmemError`` to isolate "our" failures from genuine bugs (which should
keep propagating). Provider failures split into Transient (retry may help) and
Permanent (retry will not help) so the retry layer can decide without guessing.
"""
from __future__ import annotations


class MarkmemError(Exception):
    """Base class for every error markmem raises on purpose."""


class ConfigError(MarkmemError):
    """Invalid, missing, or contradictory configuration (env / profile / path)."""


class StorageError(MarkmemError):
    """The derived store (vector SQLite, graph, tier cache) could not be read/written.

    The Markdown corpus stays the source of truth; a StorageError means an index
    is unusable and should be rebuilt, not that data was lost.
    """


class RetrievalError(MarkmemError):
    """Retrieval could not complete at all.

    Note: a *degraded* retrieval (e.g. vector leg down, BM25 still answering) is
    NOT an error — it returns results flagged ``degraded``. This is raised only
    when no leg can answer.
    """


class ProviderError(MarkmemError):
    """An external provider failed — e.g. the Ollama embedding endpoint."""


class TransientProviderError(ProviderError):
    """A retry may succeed: timeout, connection reset, HTTP 5xx, model loading."""


class PermanentProviderError(ProviderError):
    """A retry will not help: HTTP 4xx, malformed request, unknown model."""
