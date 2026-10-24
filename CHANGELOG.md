# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Added
- English README as the canonical version; the German edition moves to `README.de.md`.
- `SECURITY.md`, `THREAT_MODEL.md`, `CODE_OF_CONDUCT.md`, and GitHub issue / pull-request templates.
- Governance-first positioning ("an AI memory an auditor can read") and an honest, non-FUD comparison table.
- English `CONTRIBUTING.md` (German kept as `CONTRIBUTING.de.md`).

### Changed
- Recall@1 figures now carry an explicit caveat: private corpus, n ≈ 30–35, not an independent public
  benchmark. A reproducible public benchmark (held-out split, significance tests, published harness) is on the roadmap.

## [0.1.0] - 2026-06-26

Erste öffentliche Version. Ein selbst-lernendes, selbst-tunendes KI-Gedächtnis auf Markdown + git.

### Hinzugefügt

- **Markdown + git als Quelle der Wahrheit** — alle Indizes (Vektor, Graph, Tiers) abgeleitet und jederzeit neu baubar.
- **HybridRAG-Abruf** (`markmem-retrieve`) — BM25 ⊕ Entity-Graph ⊕ Vektor (bge-m3) mit gewichtetem Reciprocal Rank Fusion, optionalem Confidence-Prior und opt-in Cross-Encoder-Rerank (`bge-reranker-v2-m3`).
- **Embedded Vektor-Store** — Ollama bge-m3 (1024d) + SQLite-BLOB + numpy-Brute-Force-Cosine, fail-open, kein Milvus/ANN.
- **Indexer** (`markmem-index`) — voll/inkrementell, Stale-Chunk-Disziplin, Secret-Redaktion, Chunk-Cap.
- **Zwei-Kanal-Laden** — Verhaltensregeln über einen eigenen Hook-Kanal injiziert; `MEMORY.md` bleibt unter dem Lade-Limit, Hard-Gates werden nie abgeschnitten.
- **Tiering** (`markmem-tier`) — verlustfreies Hot → Warm, Pressure-Warnung.
- **Verdichtung** (`markmem-compact`) — Nachbar-Retrieval → LLM-Vorschlag ADD/MERGE/SUPERSEDE/DROP, immer mit Review-Gate, Anti-Halluzinations-Validierung.
- **Lern-Schleife** — Korrektur (aus Diff), Surprise, Outcome-Confidence-Propagation, Kalibrierung sowie ein **Dead-End-Katalog** (`markmem-deadends`) mit **aktiver Hemmung** (warnt instant bei Sackgassen-ähnlichem Ziel).
- **Eval-Harness** (`markmem-eval`) — Recall@1 / MRR gegen ein keyword-freies Paraphrase-Gold-Set, A/B + Rerank.
- **Selbst-Tuner** (`markmem-tune`) — Grid-Search der RRF-Gewichte + Confidence-Prior gegen Recall@1, schreibt versionierte `retrieval_config.json`.
- **Graph-Verdichtung** (`markmem-graph`) — Entity-Knoten + Ko-Okkurrenz-Kanten.
- **Integrität & Status** (`markmem-audit`, `markmem-status`) — Hash-Ledger, Ghost-GC, Orphan-Cluster, Token-Ökonomie-Sensor, One-Screen-Pulse-Check.
- **memDash** (`memdash`) — responsives, farbiges Live-Terminal-Dashboard; drei Layout-Modi (schmal/mittel/breit) wie Media-Queries, Unicode-korrekte Breitenrechnung (wcwidth), Farb-Degradation Truecolor → 256 → 16 → S/W, kein Daemon.
- **Konfiguration** — alle Werte über `MARKMEM_*`-Env-Variablen (Env > Profil > Default); mitgelieferte Profile `generic` und `bugbounty`.
- **Claude-Code-Integration** — Beispiel-Hooks (SessionStart/PreToolUse/PostToolUse/Stop) unter `integrations/claude_code/`.
- **Dokumentation** — Architektur, Retrieval, Lern-Schleife, Self-Tuning, Konfiguration.

### Entwurfs-Entscheidungen (gemessen statt behauptet)

- **Confidence-Prior** gebaut, aber als Default **aus** — der Tuner maß `conf_beta = 0` (wirkungslos auf dem getesteten Korpus). Infrastruktur bleibt dormant.
- **Reranker** als **opt-in**, nicht Default — +6,6 % Recall@1, aber 20–60 s CPU.

[Unreleased]: https://github.com/markmem/markmem/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/markmem/markmem/releases/tag/v0.1.0
