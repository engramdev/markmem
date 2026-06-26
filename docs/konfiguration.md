# Konfiguration

Alle Einstellungen werden in der Reihenfolge **Env-Variable > Profil-TOML > Default** aufgelöst. Out of the box zeigen alle Defaults auf den mitgelieferten `examples/`-Korpus, sodass `markmem` ohne jede Konfiguration auf synthetischen Demo-Daten läuft. Für ein eigenes Gedächtnis genügt in der Regel `MARKMEM_MEMORY_DIR`.

`markmem` ist überall **fail-open**: fehlt eine Einstellung, greift der Default — nie ein harter Abbruch wegen Config. Die aufgelöste Konfiguration lässt sich über `markmem-status` bzw. `markmem.config.info()` einsehen.

---

## Kern-Pfade

| Env-Variable | Default | Bedeutung |
|---|---|---|
| `MARKMEM_MEMORY_DIR` | `examples/memory` | Wurzel des Gedächtnisses (Markdown-Karten). **Die wichtigste Variable.** |
| `MARKMEM_GRAPH` | `examples/graph/graph.json` | Entity-/Wikilink-Graph (JSON) |
| `MARKMEM_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama-Endpoint für Embeddings |

Von `MARKMEM_MEMORY_DIR` abgeleitet (nicht direkt setzbar): `metrics/` (Index, Eval, Kalibrierung), `inbox/`, `retrieval_config.json`, sowie die Verfassungs-Dateien `MEMORY.md`, `MEMORY_RULES.md`, `MEMORY_DEEP.md`, `MEMORY_INFRA.md`.

---

## Modelle

| Env-Variable | Default | Bedeutung |
|---|---|---|
| `MARKMEM_EMBED_MODEL` | `bge-m3` | Embedding-Modell (Ollama), multilingual DE+EN |
| `MARKMEM_EMBED_DIM` | `1024` | Embedding-Dimension (muss zum Modell passen) |
| `MARKMEM_LLM_MODEL` | `dolphin-llama3:8b` | lokales LLM für Verdichtungs-Triage |
| `MARKMEM_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | Cross-Encoder für den opt-in-Rerank |

> **Achtung:** Ein Wechsel des Embedding-Modells/der Dimension (z. B. 768d ↔ 1024d) erfordert einen **Voll-Reindex** — die Vektoren sind nicht kompatibel.

---

## Domänen-Einstellungen (Env > Profil > Default)

Diese Werte generalisieren `markmem` über die ursprüngliche Domäne hinaus. Sie lassen sich pro Profil setzen.

| Env-Variable | Default (generic) | Bedeutung |
|---|---|---|
| `MARKMEM_DEADEND_DIR` | `examples/deadend_sources/nieten` | Quell-Verzeichnis für den Dead-End-/Negativ-Wissen-Katalog |
| `MARKMEM_DEADEND_GLOB` | `*/DEADEND.md` | Glob, der eine Sackgassen-Datei erkennt |
| *(Profil)* `deadend.registry_name` | `reference_deadends_registry.md` | Name des generierten Dead-End-Registers |
| `MARKMEM_ENTITY_SOURCE` | `dir` | Entity-Quelle für die Graph-Verdichtung: `dir` \| `file` \| `list` |
| `MARKMEM_ENTITY_DIR` | `examples/memory` | Verzeichnis, aus dem Entities gezogen werden (bei `source=dir`) |
| `MARKMEM_ENTITY_FILE` | *(leer)* | Datei mit Entities (bei `source=file`) |
| *(Profil)* `entity.list` | `[]` | feste Entity-Liste (bei `source=list`) |
| *(Profil)* `entity.generic` | `test, demo, example, sample, temp, todo, misc, data` | Stoppwörter, die nicht als Entity-Namensteil zählen |
| *(Profil)* `context.patterns` | `[["/projects/([a-z0-9_-]+)", "project"]]` | cwd→Kontext-Pattern für die Hook-Integration (`[regex, tag]`) |

---

## Profile

Ein Profil wird über `MARKMEM_PROFILE` gewählt — entweder als Name (lädt `examples/profiles/<name>.toml`) oder als direkter Pfad zu einer `.toml`-Datei.

| Profil | Zweck |
|---|---|
| `generic` *(Default)* | domänenneutral — Standardwerte oben |
| `bugbounty` *(Beispiel)* | reproduziert die ursprüngliche Security-Research-Semantik (eigene Dead-End-/Entity-/Kontext-Regeln) |

```bash
export MARKMEM_PROFILE=generic
# oder ein eigenes Profil per Pfad:
export MARKMEM_PROFILE=/pfad/zu/mein_profil.toml
```

Ein eigenes Profil ist eine TOML-Datei mit den oben kursiv markierten Schlüsseln, z. B.:

```toml
[deadend]
dir = "deadend_sources/meine"
glob = "*/SACKGASSE.md"
registry_name = "reference_deadends_registry.md"

[entity]
source = "dir"
generic = ["test", "demo", "intern"]

[context]
patterns = [["/repos/([a-z0-9_-]+)", "repo"]]
```

---

## memDash-Overrides

Das Dashboard liest zusätzlich diese Variablen (nützlich zum Testen der responsiven Modi):

| Variable | Werte | Wirkung |
|---|---|---|
| `COLUMNS` | Zahl | erzwingt eine Terminalbreite |
| `MEMDASH_MODUS` | `schmal` \| `mittel` \| `breit` | erzwingt einen Layout-Modus |
| `MEMDASH_FARBEN` | `aus` | schaltet Farben ab (S/W) |

```bash
COLUMNS=40 MEMDASH_MODUS=schmal MEMDASH_FARBEN=aus memdash
```

---

## Datenschutz

Die `.gitignore` verhindert bereits, dass private Daten ins Repo geraten: `/memory/`, `/data/`, `*.private.md`, alle `*.sqlite`-Indizes, generierte Metriken und `retrieval_config.json` sind ausgeschlossen. Reale Notizen liegen außerhalb des Repos (per `MARKMEM_MEMORY_DIR`) und bleiben privat. Siehe [CONTRIBUTING.md](../CONTRIBUTING.md).
