# Mitwirken an markmem

Danke für dein Interesse. `markmem` ist bewusst klein, ehrlich und gut messbar gehalten — Beiträge sollten das fortführen.

## Setup

```bash
git clone <repo>
cd markmem
pip install -e ".[vektor,dev]"   # Vektor-Bein + pytest/ruff
ollama pull bge-m3               # für das Vektor-Bein und Evals
```

Schneller Funktions-Check auf dem Demo-Korpus:

```bash
bash examples/quickstart.sh
```

## Tests

```bash
pytest                    # Kern-Tests
pytest -m "not rerank"    # ohne torch/transformers
pytest -m "not ollama"    # ohne laufenden Ollama
ruff check .              # Linting (line-length 120, target py311)
```

Tests, die externe Dienste brauchen, sind markiert (`rerank`, `ollama`) und werden ohne diese sauber übersprungen.

## Stil

- **Code:** Python 3.11+, pure stdlib im Kern; schwere Abhängigkeiten (numpy, torch, transformers) nur hinter optionalen Extras und **fail-open** importieren — fehlt das Extra, degradiert die Funktion, statt abzustürzen.
- **Kommentare & Doku-Strings auf Deutsch**, knapp und sachlich.
- **Namen ≥ 4 Zeichen**, sprechend (keine `x`, `tmp`, `d` als tragende Variablen).
- **fail-open beim Abruf, fail-closed bei riskanten Schreib-Aktionen.** Ein Synapsen-Fehler darf nie die Session blockieren.
- **Verhaltensänderndes Wissen nie auto-schreiben** — immer als Vorschlag durch ein Review-Gate.
- **Jede Leistungsbehauptung ist eine gemessene Zahl** (Eval-Harness), kein Versprechen. „Klingt klug" zählt nicht, „ist messbar besser" zählt.

## Privacy-Regel (verbindlich)

**Niemals reale Daten committen.** Konkret:

- Nur synthetische `*.sample.md`-Karten und die Demo-Index-Dateien unter `examples/` gehören ins Repo.
- Reale Memory-Datenbanken, private Notizen, echte Ziel-/Personen-/Projektnamen, Secrets, API-Keys und generierte Indizes bleiben **draußen** (sie sind per `.gitignore` blockiert: `/memory/`, `/data/`, `*.private.md`, `*.sqlite`, Metriken).
- Vor jedem Commit: Diff sichten — keine echten Daten, kein Secret. Der Indexer redigiert Secrets vor dem Einbetten; verlass dich trotzdem nicht allein darauf.

## Pull Requests

- kleine, nachvollziehbare, rückbaubare Schritte,
- Tests grün, `ruff` sauber,
- bei Retrieval-/Tuning-Änderungen: Eval-Zahlen vorher/nachher beilegen,
- Doku mitziehen, wenn sich Verhalten oder Config ändert.
