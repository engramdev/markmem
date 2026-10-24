#!/usr/bin/env python3
"""
memory_compact.py — Verdichtungs-Engine (Gedächtnis-v3, Phase 2, Mem0-Logik).

Problem: Inbox-Stau (60+ Roh-Cluster). Bestehende Triage clustert nur — sie
entscheidet NICHT, ob ein Cluster (a) Rauschen ist, (b) schon in einer Karte
steht, oder (c) eine neue Lehre verdient. Genau das ist Verdichten statt Anhäufen.

Mem0-Prinzip: pro Cluster die ÄHNLICHSTEN bestehenden Karten holen (Nachbar-
Retrieval), dann ein LLM EINE Operation wählen lassen:
  DROP   — kein dauerhaftes, wiederverwendbares Wissen (Einmal-Debug/Frage/Geplauder)
  MERGE  — Wissen steckt schon in einer bestehenden Karte (→ nennt sie)
  ADD    — neue dauerhafte Lehre (→ Titel + verdichteter Karten-Entwurf)

SICHERHEIT: schreibt AUSSCHLIESSLICH Vorschläge nach inbox/compaction_proposals.md.
Mutiert NIE eine bestehende Karte. Mensch entscheidet final via /memory-review.
Hybrid-LLM: lokales dolphin (Masse/Triage); die heiklen MERGE/ADD-Entwürfe prüft
der Mensch/Claude beim Review (Cloud-Review-Stufe).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime

from markmem import paths
from markmem.config import LLM_MODEL, MEMORY_DIR
from markmem.core import find_related_memories as frm  # Nachbar-Retrieval (dedup-coverage) wiederverwenden
from markmem.core import llm_client

DIGEST = paths.INBOX / "triage_digest.md"
OUT = paths.INBOX / "compaction_proposals.md"

PROMPT = """Du bist ein präziser Memory-Kurator für eine Bug-Bounty-Wissensbasis.
Gegeben: ein Themen-Cluster aus Roh-Notizen + die ähnlichsten BESTEHENDEN Karten.
Wähle GENAU EINE Aktion:
- DROP: kein dauerhaftes, wiederverwendbares Wissen (Einmal-Debugging, Frage, Geplauder, Status-Geschwätz).
- MERGE: die Lehre steckt bereits in einer bestehenden Karte → gib deren Dateinamen als target.
- ADD: echte, dauerhafte, wiederverwendbare Lehre, die noch fehlt → gib Titel + verdichteten Body (2-4 Sätze).

Antworte AUSSCHLIESSLICH als kompaktes JSON, nichts davor/danach:
{{"decision":"DROP|MERGE|ADD","target":"<datei.md oder leer>","rationale":"<1 Satz>","title":"<nur bei ADD>","body":"<nur bei ADD, 2-4 Sätze>"}}

CLUSTER:
{cluster}

ÄHNLICHSTE BESTEHENDE KARTEN:
{neighbors}
"""


def generate(prompt: str, timeout: int = 90) -> str | None:
    """Observable, fail-open LLM call (shared client)."""
    return llm_client.generate(prompt, timeout=timeout, temperature=0.1)


def parse_clusters(text: str) -> list[dict]:
    """→ [{'theme':..., 'items':[quotes]}] aus triage_digest.md."""
    clusters = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^## Cluster \d+ — (.*?)\s*\(\d+ items?\)", line)
        if m:
            if cur:
                clusters.append(cur)
            cur = {"theme": m.group(1).strip(), "items": []}
        elif cur is not None:
            q = re.match(r"^\s*>\s?(.*)", line)
            if q and q.group(1).strip():
                cur["items"].append(q.group(1).strip())
    if cur:
        clusters.append(cur)
    return clusters


def extract_json(s: str) -> dict | None:
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def real_files() -> set[str]:
    """Reale Memory-Dateinamen — zum Erkennen halluzinierter MERGE-Ziele."""
    return {p.name for p in MEMORY_DIR.glob("*.md")}


def validate_target(dec: dict, neighbors: list[dict], files: set[str]) -> None:
    """Härtung gegen LLM-Halluzination: existiert das MERGE-Ziel nicht real, auf den
    obersten echten Nachbarn korrigieren; gibt es keinen, MERGE→ungewiss markieren.
    In-place auf dec."""
    if (dec.get("decision") or "").upper() != "MERGE":
        return
    tgt = (dec.get("target") or "").strip()
    if tgt in files:
        return
    real_neigh = [n["file"] for n in neighbors if n["file"] in files]
    if real_neigh:
        dec["target"] = real_neigh[0]
        dec["target_corrected"] = f"(LLM nannte '{tgt or '—'}' — korrigiert auf realen Nachbarn)"
    else:
        dec["decision"] = "MERGE?"
        dec["target_corrected"] = f"(LLM-Ziel '{tgt or '—'}' existiert nicht + kein realer Nachbar — Mensch prüfen)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=0, help="nur N Cluster verarbeiten (0=alle)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not DIGEST.exists():
        print(f"[error] kein triage_digest.md ({DIGEST})", file=sys.stderr)
        return 1
    if generate("ping", timeout=120) is None:  # 120s: Kaltstart (4.6GB-Modell laden)
        print(f"[error] LLM ({LLM_MODEL}) nicht erreichbar.", file=sys.stderr)
        return 1

    clusters = parse_clusters(DIGEST.read_text(encoding="utf-8"))
    if args.max:
        clusters = clusters[: args.max]
    if not args.quiet:
        print(f"[plan] {len(clusters)} Cluster zu verdichten (LLM={LLM_MODEL}, Nachbar-Retrieval an).")

    files = real_files()
    stats = {"DROP": 0, "MERGE": 0, "ADD": 0, "?": 0}
    halluc = 0
    proposals = []
    for i, c in enumerate(clusters, 1):
        rep = c["theme"] + "\n" + "\n".join(c["items"][:5])[:1500]
        try:
            neigh = frm.find_for_text(rep, k=5, min_score=0.15)
        except Exception:
            neigh = []
        neigh_str = "\n".join(f"- {n['file']} (überlappung {n['score']})" for n in neigh) or "(keine ähnliche Karte)"
        out = generate(PROMPT.format(cluster=rep[:1800], neighbors=neigh_str))
        dec = extract_json(out or "") or {}
        validate_target(dec, neigh, files)  # Härtung gegen halluzinierte MERGE-Ziele
        if dec.get("target_corrected"):
            halluc += 1
        d = (dec.get("decision") or "?").upper()
        if d not in stats:
            d = "?"
        stats[d] += 1
        proposals.append({"theme": c["theme"], "n_items": len(c["items"]), "dec": dec, "neighbors": [n["file"] for n in neigh]})
        if not args.quiet and i % 5 == 0:
            print(f"  … {i}/{len(clusters)}  (DROP {stats['DROP']} · MERGE {stats['MERGE']} · ADD {stats['ADD']})")

    # Vorschläge schreiben (NUR Vorschlag — kein Karten-Write)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Verdichtungs-Vorschläge (memory_compact.py, {stamp})",
             "",
             f"> {len(clusters)} Cluster verdichtet · DROP {stats['DROP']} · MERGE {stats['MERGE']} · ADD {stats['ADD']} · unklar {stats['?']} · {halluc} halluzinierte Ziele korrigiert",
             "> Mensch entscheidet pro Vorschlag via `/memory-review`. Nichts wurde automatisch geschrieben.",
             ""]
    for p in proposals:
        dec = p["dec"]; d = (dec.get("decision") or "?").upper()
        icon = {"DROP": "🗑", "MERGE": "🔀", "ADD": "➕"}.get(d, "❓")
        lines.append(f"## {icon} {d} — {p['theme']}  ({p['n_items']} items)")
        if dec.get("rationale"):
            lines.append(f"- Grund: {dec['rationale']}")
        if d == "MERGE" and dec.get("target"):
            lines.append(f"- → MERGE in: `{dec['target']}`")
        if dec.get("target_corrected"):
            lines.append(f"- ⚠ {dec['target_corrected']}")
        if d == "ADD":
            lines.append(f"- Titel: **{dec.get('title','(kein)')}**")
            if dec.get("body"):
                lines.append(f"- Entwurf: {dec['body']}")
        if p["neighbors"]:
            lines.append(f"- Nachbarn: {', '.join(p['neighbors'][:4])}")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")

    if not args.quiet:
        print(f"[done] {len(clusters)} Cluster → {OUT}")
        print(f"  DROP {stats['DROP']} · MERGE {stats['MERGE']} · ADD {stats['ADD']} · unklar {stats['?']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
