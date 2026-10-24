#!/usr/bin/env python3
"""
vector_store.py — Leichtgewichtiges Semantik-Bein für den Memory-Pool.

Gedächtnis-v3, Phase 0+1. Ersetzt das tote Milvus/claude-context-Setup durch
einen embedded Store: Ollama (bge-m3, 1024d) für Embeddings + plain SQLite (BLOB)
für Persistenz + numpy-Brute-Force-Cosine für die Suche.

Begründung (Profi-Call, siehe handoff/gedaechtnis-architektur-v3-synthese.md):
  - Bei wenigen tausend Vektoren ist Brute-Force-Cosine < 10ms → unschlagbar
    einfach, kann nicht brechen (kein ANN-Tuning, kein Daemon, kein OOM wie Milvus).
  - Plain SQLite (kein sqlite-vec-Extension) = null Portabilitätsrisiko, numpy ist
    bereits vorhanden. sqlite-vec bleibt Drop-in-Option ab ~50k Vektoren.
  - Embeddings werden NORMALISIERT gespeichert → Suche = reines Dot-Product.

Markdown+git bleibt Quelle der Wahrheit; dieser Index ist abgeleitet und jederzeit
über embed_memories.py --rebuild neu baubar.

Fail-open by design: Wenn Ollama/Index/numpy fehlen, geben die Funktionen []/None
zurück statt zu werfen — der Aufrufer (memory_retrieve.py) läuft dann ohne Semantik-Bein.
"""
from __future__ import annotations

import json
import sqlite3
import struct
import sys
import urllib.error
import urllib.request

from markmem import paths
from markmem.config import EMBED_MODEL, OLLAMA_URL
from markmem.logging import get_logger

log = get_logger(__name__)

DB_PATH = paths.VECTOR_INDEX
_OLLAMA_TIMEOUT = 45  # s — bge-m3 auf CPU; mit Chunk-Cap (≤3000 Z.) bleiben Aufrufe < ~15s

# Observability: fail-open stays transparent to the caller, but loud to the operator.
_STATS: dict[str, int] = {
    "embed_http_error": 0,
    "embed_conn_error": 0,
    "embed_bad_response": 0,
    "embed_count_mismatch": 0,
}
_warned: set[str] = set()


def stats() -> dict[str, int]:
    """Snapshot of the embed-failure counters (observable fail-open)."""
    return dict(_STATS)


def _note_degraded(reason: str) -> None:
    """Log ONCE per process that the vector leg is unavailable. Not an error:
    retrieval correctly falls back to BM25 + entity."""
    if reason not in _warned:
        _warned.add(reason)
        log.info("vector leg unavailable (%s); retrieval uses BM25+entity only", reason)


def available() -> bool:
    """True if the vector leg can even run: numpy importable AND an index file exists.
    Lets a caller tell 'vector leg down' apart from 'vector leg found nothing' (both
    otherwise surface as an empty result). A live Ollama is NOT checked here -- an
    embedding failure despite an index is caught via the stats() counters."""
    return _np() is not None and DB_PATH.exists()


# --------------------------------------------------------------- Ollama -------
KEEP_ALIVE = "1h"  # bge-m3 nach Nutzung geladen halten → schnelles On-Demand-Retrieval


def _embed_call(texts: list[str], model: str, timeout: int) -> list[list[float]] | None:
    """One /api/embed call. Returns None on any failure so the caller stays fail-open --
    but every failure is now logged (never with the input text) and counted.

    `truncate` is set explicitly. True preserves Ollama's default (trim an over-long
    input rather than error); markmem's chunk cap keeps inputs well under the model
    window, so it should not trigger -- setting it documents the intent."""
    payload = json.dumps(
        {"model": model, "input": texts, "keep_alive": KEEP_ALIVE, "truncate": True}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # subclass of URLError -- catch first
        _STATS["embed_http_error"] += 1
        log.warning("embed call failed: HTTP %s (%s); vector leg degrades to lexical",
                    exc.code, "transient" if exc.code >= 500 else "permanent")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _STATS["embed_conn_error"] += 1
        log.warning("embed call failed: %s (is ollama up at %s?); degrading to lexical",
                    type(exc).__name__, OLLAMA_URL)
        return None
    except json.JSONDecodeError:
        _STATS["embed_bad_response"] += 1
        log.warning("embed call returned malformed JSON; degrading to lexical")
        return None
    vecs = data.get("embeddings")
    if not vecs or len(vecs) != len(texts):
        _STATS["embed_count_mismatch"] += 1
        log.debug("embed returned %s vectors for %s inputs; retrying per-text",
                  len(vecs) if vecs else 0, len(texts))
        return None
    return vecs


def embed(texts: list[str], *, model: str = EMBED_MODEL,
          timeout: int = _OLLAMA_TIMEOUT) -> list[list[float]] | None:
    """Embedde eine Liste von Texten über Ollamas /api/embed.
    Robust: scheitert der Batch (Token-Budget-Überlauf → Ollama liefert zu wenige
    Vektoren), wird automatisch pro Text einzeln nachgeholt (Einzel-Embeds sind
    zuverlässig). None nur, wenn ein einzelner Text wirklich nicht embedbar ist."""
    if not texts:
        return []
    got = _embed_call(texts, model, timeout)
    if got is not None:
        return got
    # Fallback: Text-für-Text (isoliert die eine problematische Sektion)
    out: list[list[float]] = []
    for t in texts:
        single = _embed_call([t], model, timeout)
        if not single:
            return None
        out.append(single[0])
    return out


def embed_one(text: str, *, model: str = EMBED_MODEL,
              timeout: int = 10) -> list[float] | None:
    out = embed([text], model=model, timeout=timeout)
    return out[0] if out else None


# ------------------------------------------------------------- Numpy ----------
def _np():
    """numpy lazy importieren — fehlt es, läuft das System ohne Vektor-Bein weiter."""
    try:
        import numpy as np  # type: ignore
        return np
    except Exception:
        return None


def _pack(vec: list[float]) -> bytes:
    """float-Liste → normalisierter float32-BLOB (L2-Norm = 1 → Cosine = Dot)."""
    np = _np()
    if np is not None:
        a = np.asarray(vec, dtype="float32")
        n = float(np.linalg.norm(a))
        if n > 0:
            a = a / n
        return a.tobytes()
    # Fallback ohne numpy (nur fürs Schreiben, langsam)
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return struct.pack(f"<{len(vec)}f", *[x / norm for x in vec])


# ------------------------------------------------------------- SQLite ---------
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS chunks (
  id          INTEGER PRIMARY KEY,
  file        TEXT NOT NULL,
  section     TEXT DEFAULT '',
  text        TEXT NOT NULL,
  content_sha TEXT NOT NULL,
  mtime       REAL,
  embedding   BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file);
"""


def connect(create: bool = False) -> sqlite3.Connection | None:
    if not DB_PATH.exists() and not create:
        return None
    if create:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    if create:
        con.executescript(SCHEMA)
    return con


def get_meta(con: sqlite3.Connection, key: str) -> str | None:
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))


# --------------------------------------------------------------- Search -------
def search(query: str, *, k: int = 12, exclude: str | None = None,
           timeout: int = 10) -> list[tuple[str, float]]:
    """Semantische Suche → [(file, score)] pro DATEI (bester Chunk je Datei),
    nach Cosine absteigend. Fail-open: gibt [] bei jedem fehlenden Baustein.
    timeout: kurz halten (z.B. 3s) für latenzkritische Pfade wie den SessionStart-Hook."""
    np = _np()
    if np is None:
        _note_degraded("numpy not installed")
        return []
    con = connect()
    if con is None:
        _note_degraded("no vector index built")
        return []
    try:
        rows = con.execute("SELECT file, embedding FROM chunks").fetchall()
    except sqlite3.Error as exc:
        con.close()
        log.warning("vector index read failed (%s); degrading to lexical", type(exc).__name__)
        return []
    con.close()
    if not rows:
        _note_degraded("vector index empty")
        return []

    qv = embed_one(query, timeout=timeout)
    if qv is None:
        return []
    q = np.asarray(qv, dtype="float32")
    qn = float(np.linalg.norm(q))
    if qn == 0:
        return []
    q = q / qn

    # Matrix aus gespeicherten (bereits normalisierten) Vektoren
    files: list[str] = []
    mat = np.frombuffer(b"".join(r[1] for r in rows), dtype="float32")
    dim = q.shape[0]
    if mat.size % dim != 0:
        log.warning("vector index dim mismatch (stale index -- rebuild with markmem-index); "
                    "skipping vector leg")
        return []  # Dim-Mismatch (z.B. alter Index) → fail-open
    mat = mat.reshape(-1, dim)
    files = [r[0] for r in rows]

    sims = mat @ q  # Cosine, da alles L2-normalisiert
    best: dict[str, float] = {}
    for f, s in zip(files, sims):
        if f == exclude:
            continue
        sc = float(s)
        if sc > best.get(f, -2.0):
            best[f] = sc
    ranked = sorted(best.items(), key=lambda x: x[1], reverse=True)[:k]
    return ranked


# --------------------------------------------------------------- CLI ----------
def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Semantische Suche über den Memory-Vektor-Index")
    ap.add_argument("--query", required=True)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"[error] kein Index: {DB_PATH} — erst embed_memories.py --rebuild", file=sys.stderr)
        return 1
    res = search(args.query, k=args.k)
    if args.json:
        print(json.dumps([[f, round(s, 4)] for f, s in res], ensure_ascii=False, indent=2))
        return 0
    if not res:
        print("(keine Treffer — Ollama erreichbar? bge-m3 gezogen? Index gebaut?)")
        return 0
    print(f"Semantik-Treffer für: \"{args.query}\"")
    print(f"{'cos':>6}  file")
    print(f"{'-----':>6}  {'-' * 44}")
    for f, s in res:
        print(f"  {s:.4f}  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
