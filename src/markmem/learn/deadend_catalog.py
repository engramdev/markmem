#!/usr/bin/env python3
"""
deadend_catalog.py — Dead-End-/Negativ-Wissen-Katalog (Gedächtnis-v3 Lern-Schicht).

"Der unterschätzteste Hebel": fast jedes Memory speichert, was FUNKTIONIERT hat —
kaum eines, was NICHT funktioniert hat. Folge: dieselbe Sackgasse wird Wochen später
wieder vorgeschlagen. Negativ-Wissen ist genauso wertvoll wie Positiv-Wissen.

Quelle der Dead-Ends: die DEADEND.md-Write-ups unter config.DEADEND_DIR (read-only;
die Quell-Bäume sind geschützt — wir LESEN nur). Daraus wird ein semantisch
indizierbares Register: pro Dead-End eine Sektion (## <entity>) → embed_memories
zerlegt das in per-Entity-Chunks → jeder Dead-End ist EINZELN semantisch abrufbar.

Deterministisch (kein LLM): die DEADEND.md sind strukturiert (Verdikt/Re-Approach/
Lehre). Robust gegen Formatabweichung (Fallback: erste Absätze).

Output: paths.DEADEND_REGISTRY (type reference, indiziert).
Read-only gegenüber den Quell-Bäumen. Idempotent: überschreibt nur das Register.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from markmem.config import DEADEND_DIR, DEADEND_GLOB
from markmem import paths

OUT = paths.DEADEND_REGISTRY


def section(text: str, *keys: str) -> str | None:
    """Hole den Body der ersten ## -Sektion, deren Header eines der keys enthält."""
    lines = text.splitlines()
    for i, l in enumerate(lines):
        if l.startswith("##") and any(k.lower() in l.lower() for k in keys):
            body = []
            for nl in lines[i + 1:]:
                if nl.startswith("## "):
                    break
                body.append(nl)
            b = "\n".join(body).strip()
            if b:
                return b
    return None


def first_para(text: str, n: int = 280) -> str:
    """Fallback: erster nicht-leerer Absatz nach dem Titel."""
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if p and not p.startswith("# "):
            return p[:n]
    return text[:n].strip()


def harvest_one(deadend_md: Path) -> dict | None:
    try:
        text = deadend_md.read_text(encoding="utf-8")
    except Exception:
        return None
    if not text.strip():
        return None
    entity = deadend_md.parent.name
    m = re.search(r"^#\s+(.*)", text, re.MULTILINE)
    title = m.group(1).strip() if m else entity
    # Plattform/Stack-Zeile (oft direkt unter dem Titel)
    plat = ""
    pm = re.search(r"(?im)^Plattform[:\s].*", text)
    if pm:
        plat = pm.group(0).strip()[:140]
    verdikt = section(text, "Verdikt", "Bestätigt negativ") or first_para(text)
    reapproach = section(text, "Re-Approach", "Reapproach")
    lehre = section(text, "Lehre")
    return {
        "entity": entity, "title": title, "plat": plat,
        "verdikt": (verdikt or "")[:420].strip(),
        "reapproach": (reapproach or "")[:260].strip(),
        "lehre": (lehre or "")[:200].strip(),
        "src": str(deadend_md),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()

    if not DEADEND_DIR.exists():
        print(f"[error] kein Dead-End-Verzeichnis: {DEADEND_DIR}", file=sys.stderr)
        return 1
    entries = []
    for nm in sorted(DEADEND_DIR.glob(DEADEND_GLOB)):
        e = harvest_one(nm)
        if e:
            entries.append(e)
    if not entries:
        print("[ok] keine DEADEND.md gefunden.")
        return 0

    stamp = datetime.now().strftime("%Y-%m-%d")
    out = [
        "---",
        "name: reference-deadends-registry",
        "description: Dead-End-Register — bestätigte Sackgassen aus Negativ-Wissen (nicht ohne neuen Vektor re-picken)",
        "metadata:",
        "  node_type: memory",
        "  type: reference",
        "  importance: 6",
        f"  created: {stamp}",
        f"  last_verified: {stamp}",
        "---",
        "",
        "# 🚫 Dead-End-Register (Negativ-Wissen-Katalog)",
        "",
        f"> Auto-geerntet aus `{DEADEND_GLOB}` unter `{DEADEND_DIR}` ({len(entries)} Dead-Ends, {stamp}) von "
        "`deadend_catalog.py`. Aktive Hemmung: bei Auswahl/Recon zuerst hier prüfen — "
        "diese Ansätze sind **bewiesen tot** in ihrem Kontext. Per Entity semantisch abrufbar "
        "(`memory_retrieve`) + cwd-Banner-Warnung. Re-Pick NUR mit neuem Vektor.",
        "",
    ]
    for e in entries:
        out.append(f"## {e['entity']} — Dead-End")
        if e["plat"]:
            out.append(f"- {e['plat']}")
        if e["verdikt"]:
            out.append(f"- **Tot weil:** {e['verdikt']}")
        if e["reapproach"]:
            out.append(f"- **Re-Approach nur wenn:** {e['reapproach']}")
        if e["lehre"]:
            out.append(f"- **Lehre:** {e['lehre']}")
        out.append(f"- Quelle: `{e['src']}`")
        out.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"[done] {len(entries)} Dead-Ends → {OUT} ({len('\n'.join(out).encode())//1024}KB)")
    print("  Entities:", ", ".join(e["entity"] for e in entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
