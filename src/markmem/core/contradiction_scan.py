#!/usr/bin/env python3
"""
contradiction_scan.py — semantische Widerspruchs-Erkennung (Gedächtnis-v3, selbstheilendes Wiki).

Der bestehende Audit findet STRUKTURELLE Probleme (tote Links, Größe). Er findet
NICHT, wenn zwei Karten sich INHALTLICH widersprechen (Karte A sagt X, Karte B das
Gegenteil) — der gefährlichste Memory-Defekt, weil ich dann widersprüchliches Wissen
zitiere. Das schließt diese Lücke.

Mechanismus:
  1. Pro Datei einen Repräsentanten-Vektor (Mittel der Chunk-Embeddings) aus dem
     Vektor-Index. all-pairs Cosine (numpy) → Paare die sich SEHR ähneln (gleiches
     Thema), aber nicht near-duplicate sind: Widerspruchs-KANDIDATEN.
  2. Nur diese wenigen Kandidaten gehen ans LLM (dolphin): „widersprechen sich diese
     zwei Notizen?" → ja/nein + 1 Satz.
  3. Treffer → inbox/contradictions_semantic.md (Vorschlag, review-gated). Mutiert nie.

Read-only ggü. Karten. Schreibt nur den Inbox-Report.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys

from markmem.core import vector_store as vs
from markmem.core import llm_client
from markmem.config import MEMORY_DIR, LLM_MODEL
from markmem import paths

MEM = MEMORY_DIR
OUT = paths.INBOX / "contradictions_semantic.md"
SIM_LOW, SIM_HIGH = 0.62, 0.96   # ähnlich genug (gleiches Thema), nicht near-duplicate


def llm(prompt: str, timeout: int = 90) -> str | None:
    """Observable, fail-open LLM call (shared client)."""
    return llm_client.generate(prompt, timeout=timeout, temperature=0.0)


def file_vectors():
    """→ (files, matrix) mit einem L2-normierten Mittel-Vektor pro Datei."""
    import numpy as np
    con = vs.connect()
    if con is None:
        return [], None
    rows = con.execute("SELECT file, embedding FROM chunks").fetchall()
    con.close()
    by_file: dict[str, list] = {}
    for f, emb in rows:
        by_file.setdefault(f, []).append(np.frombuffer(emb, dtype="float32"))
    files, mat = [], []
    for f, vecs in by_file.items():
        m = np.mean(np.stack(vecs), axis=0)
        n = np.linalg.norm(m)
        if n > 0:
            m = m / n
        files.append(f)
        mat.append(m)
    return files, (np.stack(mat) if mat else None)


def excerpt(f: str, n: int = 700) -> str:
    try:
        t = (MEM / f).read_text(encoding="utf-8")
        t = re.sub(r"^---.*?---", "", t, count=1, flags=re.DOTALL)
        return t.strip()[:n]
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-pairs", type=int, default=40, help="max LLM-geprüfte Kandidaten-Paare")
    args = ap.parse_args()
    import numpy as np

    if llm("ping", timeout=120) is None:
        print(f"[error] LLM {LLM_MODEL} nicht erreichbar.", file=sys.stderr)
        return 1
    files, mat = file_vectors()
    if mat is None or len(files) < 2:
        print("[error] kein Vektor-Index. Erst embed_memories.py --rebuild.", file=sys.stderr)
        return 1

    sims = mat @ mat.T
    cand = []
    for i in range(len(files)):
        for j in range(i + 1, len(files)):
            s = float(sims[i, j])
            if SIM_LOW <= s <= SIM_HIGH:
                cand.append((s, files[i], files[j]))
    cand.sort(reverse=True)
    cand = cand[: args.max_pairs]
    print(f"[plan] {len(cand)} Widerspruchs-Kandidaten (sim {SIM_LOW}-{SIM_HIGH}) → LLM-Prüfung.")

    hits = []
    for k, (s, a, b) in enumerate(cand, 1):
        prompt = ("Zwei Notizen aus einer Bug-Bounty-Wissensbasis. Widersprechen sie sich "
                  "INHALTLICH (eine behauptet etwas, die andere das Gegenteil)? Reine "
                  "Themenähnlichkeit ist KEIN Widerspruch. Antworte NUR als JSON "
                  '{"widerspruch": true|false, "grund": "<1 Satz>"}.\n\n'
                  f"NOTIZ A ({a}):\n{excerpt(a)}\n\nNOTIZ B ({b}):\n{excerpt(b)}")
        out = llm(prompt)
        m = re.search(r"\{.*\}", out or "", re.DOTALL)
        try:
            d = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            d = {}
        if d.get("widerspruch") is True:
            hits.append((s, a, b, d.get("grund", "")))
        if k % 10 == 0:
            print(f"  … {k}/{len(cand)}  ({len(hits)} Widersprüche)")

    lines = ["# Semantische Widersprüche (contradiction_scan.py)",
             "",
             f"> {len(cand)} Kandidaten geprüft · {len(hits)} mögliche Widersprüche. "
             "Mensch entscheidet via `/memory-review` welche Karte stimmt. Nichts auto-geändert.",
             ""]
    for s, a, b, grund in hits:
        lines += [f"## ⚔ {a}  ↔  {b}  (sim {s:.2f})", f"- {grund}", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[done] {len(hits)} Widersprüche → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
