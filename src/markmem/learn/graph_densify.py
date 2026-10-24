#!/usr/bin/env python3
"""
graph_densify.py — Graph-Verdichtung / Auto-Linking (Gedächtnis-v3 Frontier).

Das Entity-Bein des Retrievals ist mit wenigen Knoten schwach. Hier wird der Graph
deterministisch verdichtet: kanonische Entity-Namen (aus einer pluggbaren Quelle)
werden zu Entity-Knoten, und Karten, die zwei Entitäten GEMEINSAM nennen, erzeugen eine
Ko-Okkurrenz-Kante (relationType co_mentioned). So entsteht „über die Ecke"-
Verwandtschaft (z.B. zwei Entitäten mit gleichem Stack/gleicher Klasse).

Entity-Quelle (config.ENTITY_SOURCE):
  - "dir"  : Verzeichnisnamen unter config.ENTITY_DIR (Default, heutiges Verhalten)
  - "file" : eine Entität pro Zeile aus config.ENTITY_FILE
  - "list" : config.ENTITY_LIST (statische Liste aus dem Profil)

Sicherheit: ADDITIV (bestehende Knoten/Kanten bleiben), DEDUP, Backup vor Schreiben.
Format-treu (graph.json = JSONL: {type:entity,...} / {type:relation,...}).
Read-only ggü. der Entity-Quelle (nur Namen gelesen). Idempotent.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from markmem import config, paths

MEM = paths.MEMORY_DIR
GRAPH = config.GRAPH
SKIP = paths.SKIP_FILES

# Generische Tokens, die als Entity-Namensteil zu Falsch-Matches führen (in fast jeder Karte)
GENERIC = config.ENTITY_GENERIC


def canonical_entities() -> set[str]:
    """Kanonische Entity-Namen aus der konfigurierten Quelle (≥4 Zeichen, distinktiv).
    Entitäten, deren ALLE Namensteile generisch sind (z.B. 'test-entity'), werden verworfen."""
    raw: list[str] = []
    source = config.ENTITY_SOURCE

    if source == "file":
        fp = Path(config.ENTITY_FILE) if config.ENTITY_FILE else None
        if fp and fp.exists():
            try:
                raw = [l.strip() for l in fp.read_text(encoding="utf-8").splitlines() if l.strip()]
            except Exception:
                raw = []
    elif source == "list":
        raw = [str(x).strip() for x in (config.ENTITY_LIST or []) if str(x).strip()]
    else:  # "dir" (Default)
        base = config.ENTITY_DIR
        if base.exists():
            for d in base.iterdir():
                # Infra-/Utility-Verzeichnisse (.foo, _archive, …) sind keine Entitäten
                if not d.is_dir() or d.name.startswith((".", "_")):
                    continue
                raw.append(d.name)

    names = set()
    for nm in raw:
        nm = nm.strip()
        if len(nm) < 4:
            continue
        parts = [p for p in re.split(r"[\s_\-]+", nm.lower()) if len(p) >= 4]
        if parts and all(p in GENERIC for p in parts):
            continue  # rein generisch → Noise
        names.add(nm.lower())
    return names


def mentions(text_lower: str, name: str) -> bool:
    """name (ggf. mehrteilig via _ -) kommt im Text vor (signifikante Teile ≥4)."""
    parts = [p for p in re.split(r"[\s_\-]+", name) if len(p) >= 4]
    return bool(parts) and all(p in text_lower for p in parts)


def load_graph() -> list[dict]:
    if not GRAPH.exists():
        return []
    out = []
    for line in GRAPH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="schreiben (sonst Dry-Run)")
    ap.add_argument("--min-cooccur", type=int, default=3, help="min Karten für eine Ko-Okkurrenz-Kante")
    args = ap.parse_args()

    entities = canonical_entities()
    if not entities:
        print("[error] keine Entitäten gefunden.")
        return 1

    graph = load_graph()
    existing_ents = {str(o.get("name", "")).lower() for o in graph if o.get("type") == "entity"}
    existing_rels = {(min(o.get("from", ""), o.get("to", "")), max(o.get("from", ""), o.get("to", "")))
                     for o in graph if o.get("type") == "relation"}

    # Pro Karte: welche Entitäten nennt sie?
    cooccur: dict[tuple[str, str], int] = {}
    ent_cards: dict[str, int] = {}
    for p in MEM.glob("*.md"):
        if p.name in SKIP:
            continue
        try:
            tl = p.read_text(encoding="utf-8").lower()
        except Exception:
            continue
        present = sorted(t for t in entities if mentions(tl, t))
        for t in present:
            ent_cards[t] = ent_cards.get(t, 0) + 1
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                key = (present[i], present[j])
                cooccur[key] = cooccur.get(key, 0) + 1

    new_ents = [t for t in ent_cards if t not in existing_ents]
    new_rels = [(a, b, n) for (a, b), n in cooccur.items()
                if n >= args.min_cooccur and (a, b) not in existing_rels]

    print(f"[plan] Entitäten gesamt: {len(entities)} · in Karten genannt: {len(ent_cards)}")
    print(f"  neue Entity-Knoten: {len(new_ents)} (Graph hatte {len(existing_ents)})")
    print(f"  neue Ko-Okkurrenz-Kanten: {len(new_rels)}")
    top = sorted(new_rels, key=lambda x: x[2], reverse=True)[:8]
    for a, b, n in top:
        print(f"    {a} ↔ {b}  ({n} Karten)")

    if not args.apply:
        print("\n[dry-run] Mit --apply schreiben (Backup wird erstellt).")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    GRAPH.parent.mkdir(parents=True, exist_ok=True)
    if GRAPH.exists():
        shutil.copy2(GRAPH, GRAPH.with_suffix(f".json.bak.{stamp}"))
    lines = [json.dumps(o, ensure_ascii=False) for o in graph]
    for t in new_ents:
        lines.append(json.dumps({"type": "entity", "name": t, "entityType": "entity",
                                 "observations": [f"auto-densify: in {ent_cards[t]} Memory-Karten genannt"]},
                                ensure_ascii=False))
    for a, b, n in new_rels:
        lines.append(json.dumps({"type": "relation", "from": a, "to": b,
                                 "relationType": "co_mentioned",
                                 "observations": [f"gemeinsam in {n} Karten"]}, ensure_ascii=False))
    GRAPH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[apply] +{len(new_ents)} Knoten, +{len(new_rels)} Kanten. Backup graph.json.bak.{stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
