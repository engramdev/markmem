#!/usr/bin/env bash
# quickstart.sh — markmem in einem Durchlauf auf dem synthetischen Demo-Korpus.
#
# Zeigt die ganze Kette: Index -> Retrieve -> Eval -> Dashboard, komplett ohne
# private Daten. Alle Daten unter examples/ sind erfunden/harmlos.
#
# HINWEIS zu den Vektor-Schritten:
#   Der Index-Aufbau (embed) und das semantische Retrieval brauchen einen lokal
#   laufenden Ollama mit dem Modell bge-m3:
#       ollama pull bge-m3   &&   ollama serve   (http://127.0.0.1:11434)
#   Fehlt Ollama, ist das System fail-open: das Retrieval läuft dann allein auf
#   BM25 + Entity-Graph weiter (--no-vectors erzwingt das ohnehin). Der
#   Eval-Modus "desc" ist deterministisch und braucht KEIN LLM.

set -euo pipefail

# Repo-Wurzel relativ zu diesem Skript (examples/ liegt direkt darunter).
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HIER/.." && pwd)"

# Demo-Korpus + Graph aktivieren (Env hat Vorrang vor Profil/Default in config.py).
export MARKMEM_MEMORY_DIR="$REPO/examples/memory"
export MARKMEM_GRAPH="$REPO/examples/graph/graph.json"
export PYTHONPATH="$REPO/src"

echo "== markmem Quickstart =="
echo "MEMORY_DIR = $MARKMEM_MEMORY_DIR"
echo "GRAPH      = $MARKMEM_GRAPH"
echo

# 1) Index (re)bauen — braucht Ollama+bge-m3. Bricht der Embed-Schritt, läuft der
#    Rest trotzdem (Retrieval fällt auf BM25+Entity zurück).
echo "-- [1/4] Vektor-Index aufbauen (Ollama+bge-m3) --"
python3 -m markmem.core.embed_memories --rebuild || \
  echo "   (Ollama/bge-m3 nicht erreichbar — weiter mit BM25+Entity, kein Vektor-Index)"
echo

# 2) Retrieval testen. Ohne Ollama: --no-vectors anhängen (rein BM25+Entity).
echo "-- [2/4] Retrieval: 'caching' --"
python3 -m markmem.core.memory_retrieve --query "caching" --k 5
echo

# 3) Eval im deterministischen desc-Modus (Query = Frontmatter-description, KEIN LLM).
echo "-- [3/4] Eval (desc-Modus, deterministisch) --"
python3 -m markmem.eval.eval_retrieval --n 5 --mode desc
echo

# 4) Dashboard-Snapshot.
echo "-- [4/4] Dashboard-Snapshot --"
python3 -m markmem.core.dashboard
