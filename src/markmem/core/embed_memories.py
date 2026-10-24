#!/usr/bin/env python3
"""
embed_memories.py — Baut/pflegt den Vektor-Index des Memory-Pools (Gedächtnis-v3).

Liest die Markdown-Memories (Quelle der Wahrheit), zerlegt sie in Chunks, holt
bge-m3-Embeddings via Ollama und speichert sie normalisiert in vector_index.sqlite.

Modi:
  --rebuild     : kompletter Neuaufbau (Tabellen leeren, alles neu embedden).
  (default)     : inkrementell — nur geänderte Dateien neu (Content-Hash-Vergleich),
                  gelöschte Dateien raus (Stale-Chunk-Schutz, eigene Prod-Lehre).

Chunking:
  - Datei ≤ 120 Zeilen → 1 Chunk (ganze Datei). Memories sind meist atomar.
  - Datei  > 120 Zeilen → Split an Markdown-Überschriften (#/##/###), Header-Pfad
    als Präfix in den Chunk-Text (verbessert Embedding-Treffer).
  - Index-Dateien (MEMORY*.md) werden NICHT embeddet (sind Navigation, kein Wissen).

Sicherheit: Secret-Scan vor dem Speichern; Treffer werden im gespeicherten Text
redigiert ([SECRET ENTFERNT]).

Read-only gegenüber den .md (verändert NIE eine Memory). Schreibt nur den Index.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
import time

from markmem import paths
from markmem.config import MEMORY_DIR
from markmem.core import vector_store as vs

SKIP_FILES = paths.SKIP_FILES
MAX_CHUNK_CHARS = 3000  # harte Obergrenze pro Chunk → jeder Embed-Aufruf < ~15s (CPU), nie Timeout.
BATCH = 8  # Embeddings pro Ollama-Request (klein → kein Token-Budget-Überlauf; Fallback in vs.embed)

# Grobe Secret-Muster (defensiv; Memories sollten nie Secrets enthalten)
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|bearer\s+[a-z0-9._-]{12,}"
    r"|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{20,})"
)


def redact(text: str) -> str:
    return SECRET_RE.sub("[SECRET ENTFERNT]", text)


def file_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _window(body: str, maxc: int) -> list[str]:
    """Zerlege einen zu langen Text an Zeilengrenzen in ≤ maxc-Fenster."""
    out: list[str] = []
    cur: list[str] = []
    n = 0
    for ln in body.splitlines(keepends=True):
        if n + len(ln) > maxc and cur:
            out.append("".join(cur))
            cur, n = [], 0
        cur.append(ln)
        n += len(ln)
    if cur:
        out.append("".join(cur))
    return out or [body]


def split_chunks(text: str) -> list[tuple[str, str]]:
    """→ [(section, chunk_text)]. Karte ≤ MAX_CHUNK_CHARS: ein Chunk. Sonst pro
    Markdown-Header; jede Sektion > MAX_CHUNK_CHARS wird zusätzlich in ≤cap-Fenster
    zerlegt (so bleibt JEDER Embed-Aufruf klein/schnell und kann nicht timeouten)."""
    text = text.strip()
    if len(text) <= MAX_CHUNK_CHARS:
        return [("", text)]

    sections: list[tuple[str, str]] = []
    cur_head = ""
    buf: list[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append((cur_head, body))

    for line in text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            flush()
            cur_head = m.group(2).strip()
            buf = [line]
        else:
            buf.append(line)
    flush()
    if not sections:
        sections = [("", text)]

    out: list[tuple[str, str]] = []
    for head, body in sections:
        prefix = f"[{head}]\n" if head else ""
        for win in _window(body, MAX_CHUNK_CHARS - len(prefix)):
            out.append((head, prefix + win.strip()))
    return out


def current_files() -> dict[str, tuple[float, str, str]]:
    """name → (mtime, sha, text) für alle embeddbaren Memories."""
    out: dict[str, tuple[float, str, str]] = {}
    for p in sorted(MEMORY_DIR.glob("*.md")):
        if p.name in SKIP_FILES:
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        out[p.name] = (p.stat().st_mtime, file_sha(txt), txt)
    return out


def indexed_shas(con: sqlite3.Connection) -> dict[str, str]:
    """name → content_sha (ein beliebiger Chunk je Datei reicht zur Diff)."""
    out: dict[str, str] = {}
    for f, sha in con.execute("SELECT file, content_sha FROM chunks GROUP BY file"):
        out[f] = sha
    return out


def embed_file(con: sqlite3.Connection, name: str, mtime: float, sha: str, text: str) -> int:
    """Embedde eine Datei (alle Chunks) und schreibe sie. Gibt Chunk-Zahl zurück.
    0 bei Embedding-Fehler (Datei wird dann übersprungen, alter Stand bleibt)."""
    pieces = split_chunks(text)
    texts = [redact(t) for _, t in pieces]
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        got = vs.embed(texts[i:i + BATCH])
        if got is None:
            return 0
        vectors.extend(got)
    con.execute("DELETE FROM chunks WHERE file=?", (name,))
    for (section, _raw), red, vec in zip(pieces, texts, vectors):
        con.execute(
            "INSERT INTO chunks(file, section, text, content_sha, mtime, embedding) "
            "VALUES(?,?,?,?,?,?)",
            (name, section, red, sha, mtime, vs._pack(vec)),
        )
    return len(pieces)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", action="store_true", help="kompletter Neuaufbau")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    def log(msg: str):
        if not args.quiet:
            print(msg)

    con = vs.connect(create=True)
    assert con is not None
    try:
        if args.rebuild:
            con.execute("DELETE FROM chunks")
            log("[rebuild] Index geleert.")

        files = current_files()
        have = {} if args.rebuild else indexed_shas(con)
        removed = [f for f in have if f not in files]
        changed = [n for n, (_, sha, _) in files.items() if have.get(n) != sha]

        # Schnellpfad: nichts geändert → sofort raus, OHNE Ollama anzufassen.
        # Macht den Aufruf im Stop-Hook latenzfrei, wenn keine Karte editiert wurde.
        if not args.rebuild and not changed and not removed:
            log("[ok] Index aktuell — nichts zu tun.")
            return 0

        # Es gibt Arbeit → jetzt erst der Ollama-Vorabcheck.
        if vs.embed_one("ping") is None:
            print("[error] Ollama/bge-m3 nicht erreichbar (http://127.0.0.1:11434, Modell bge-m3?).",
                  file=sys.stderr)
            return 1

        vs.set_meta(con, "model", vs.EMBED_MODEL)
        vs.set_meta(con, "dim", str(vs.EMBED_DIM))
        vs.set_meta(con, "updated", time.strftime("%Y-%m-%dT%H:%M:%S"))

        # Stale-Schutz: gelöschte/umbenannte Dateien aus dem Index entfernen
        for f in removed:
            con.execute("DELETE FROM chunks WHERE file=?", (f,))
        if removed:
            log(f"[stale] {len(removed)} entfernte Datei(en) aus Index gelöscht.")

        log(f"[plan] {len(files)} Memories, {len(changed)} zu (re)embedden"
            + ("" if args.rebuild else f", {len(files) - len(changed)} unverändert."))

        total_chunks = 0
        failed = 0
        for i, name in enumerate(changed, 1):
            mtime, sha, text = files[name]
            n = embed_file(con, name, mtime, sha, text)
            if n == 0:
                failed += 1
                log(f"  [skip] {name} (Embedding-Fehler)")
            else:
                total_chunks += n
            if i % 5 == 0:
                con.commit()
                log(f"  … {i}/{len(changed)}")
        con.commit()

        cnt = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        nfiles = con.execute("SELECT COUNT(DISTINCT file) FROM chunks").fetchone()[0]
        log(f"[done] {nfiles} Dateien, {cnt} Chunks im Index ({vs.EMBED_MODEL}/{vs.EMBED_DIM}d)."
            + (f" {failed} fehlgeschlagen." if failed else ""))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
