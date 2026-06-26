# markmem — Claude-Code-Integration (optional)

Dieses Verzeichnis ist das **optionale** Integrations-Modul für
[Claude Code](https://docs.anthropic.com/en/docs/claude-code). Es bindet den
generischen `markmem`-Kern an zwei Claude-Code-Hooks:

| Hook          | Skript                                   | Zweck |
|---------------|------------------------------------------|-------|
| `SessionStart`| `session_start_banner.py`                | Injiziert die Verhaltensregeln (`MEMORY_RULES.md`), zeigt einen knappen Inbox-Banner nur wenn es etwas zu tun gibt, lädt cwd-relevante + semantisch verwandte Memories, warnt vor bestätigten Dead-Ends. |
| `SessionEnd`  | `correction_synapse.py --capture`        | Macht Snapshots der Dateien, die Claude in der Session bearbeitet hat. Beim nächsten `SessionStart` (`scan`, automatisch aus dem Banner) wird erkannt, ob du sie still nachkorrigiert hast — das präziseste Lernsignal. |

Beide Skripte sind **fail-open**: jeder Fehler endet mit Exit 0, eine Session wird
nie blockiert.

`adapters.py` kapselt das eine Claude-Code-spezifische Detail (Hook-Event als JSON
auf stdin) an einer Stelle — andere Integrationen tauschen nur den Adapter.

---

## 1. markmem installieren

Variante A — als Paket (empfohlen):

```bash
pip install -e /pfad/zu/markmem      # oder: pip install markmem
```

Dann ist `import markmem` ohne `PYTHONPATH` verfügbar, und du kannst den
`PYTHONPATH`-Eintrag im `env`-Block (Schritt 3) weglassen.

Variante B — ohne Installation, direkt aus dem Repo:

```bash
export PYTHONPATH=/pfad/zu/markmem/src
```

Diesen `PYTHONPATH` setzt du dann im `env`-Block der `settings.json` (Schritt 3),
damit die Hooks `markmem` finden.

## 2. Memory-Verzeichnis wählen

`markmem` löst seinen Speicherort über Env-Variablen auf (`Env > Profil > Default`).
Ohne `MARKMEM_MEMORY_DIR` zeigt es auf den mitgelieferten `examples/memory`-Korpus
(Demo). Für echten Betrieb ein eigenes Verzeichnis setzen:

```bash
export MARKMEM_MEMORY_DIR=$HOME/.markmem/memory
mkdir -p "$MARKMEM_MEMORY_DIR/inbox" "$MARKMEM_MEMORY_DIR/metrics"
```

Optional ein Profil wählen (`examples/profiles/*.toml`) — es liefert u.a. die
cwd→Kontext-Pattern (`CONTEXT_PATTERNS`) und die Dead-End-Konfiguration:

```bash
export MARKMEM_PROFILE=generic
```

## 3. settings.json ergänzen

`settings.example.json` enthält den fertigen Ausschnitt. Übernimm `hooks` und `env`
in deine `~/.claude/settings.json` (oder die projektlokale `.claude/settings.json`)
und **ersetze die `/absolute/path/...`-Platzhalter durch echte absolute Pfade**.

- Bei pip-Installation (Variante A) kannst du den `PYTHONPATH`-Eintrag im `env`-Block
  entfernen.
- `MARKMEM_PROFILE` ist optional (Default = generisch).
- Hast du bereits andere `SessionStart`/`SessionEnd`-Hooks, füge die markmem-Einträge
  zu den vorhandenen `hooks`-Arrays hinzu, statt sie zu überschreiben.

`settings.json` erlaubt **keine Kommentare** — die Datei muss valides JSON sein.
Die Erklärungen dazu stehen hier im README.

## 4. Env setzen

Die Hooks erben die Umgebung aus dem `env`-Block der `settings.json`. Für die
manuellen Smoke-Tests unten setzt du dieselben Variablen in deiner Shell:

```bash
export PYTHONPATH=/pfad/zu/markmem/src                  # nur ohne pip-Install nötig
export MARKMEM_MEMORY_DIR=$HOME/.markmem/memory
export MARKMEM_PROFILE=generic
```

## 5. Smoke-Test (Hooks manuell mit Beispiel-JSON über stdin füttern)

Die Hooks lesen ihr Event als JSON von stdin. So testest du sie ohne Claude Code:

```bash
# SessionStart-Banner mit einer cwd (löst Kontext-Pattern aus):
echo '{"cwd":"/projects/widget-api"}' \
  | python3 integrations/claude_code/session_start_banner.py

# Banner mit leerem Event (muss trotzdem sauber durchlaufen, exit 0):
echo '{}' | python3 integrations/claude_code/session_start_banner.py
echo "exit=$?"

# SessionEnd-Capture (Transcript-Pfad optional — ohne ihn passiert nichts, exit 0):
echo '{"transcript_path":"","session_id":"smoke"}' \
  | python3 integrations/claude_code/correction_synapse.py --capture
echo "exit=$?"

# Watch-Status der Korrektur-Synapse ansehen:
python3 integrations/claude_code/correction_synapse.py --status
```

Erwartet: Der Banner gibt (sofern vorhanden) die Regeln aus `MEMORY_RULES.md` und
ggf. einen Inbox-/Kontext-Block aus; bei leerem Inbox-Zustand ist er still. In
**allen** Fällen Exit 0.

---

## Hinweise

- **Privacy:** Die Skripte enthalten keine festen Benutzerpfade oder Identitäten —
  alle Pfade kommen aus `markmem.config`/`markmem.paths` (Env/Profil). Die
  cwd-Kontext-Tags stammen aus dem gewählten Profil, nicht aus dem Code.
- **Snapshots der Korrektur-Synapse** liegen unter `$MARKMEM_MEMORY_DIR/inbox/.edit_snapshots/`
  und `.edit_state.json`. Sie sind **lokal** und dürfen nicht committet werden —
  trage sie in die `.gitignore` deines Memory-Repos ein:
  ```
  inbox/.edit_snapshots/
  inbox/.edit_state.json
  ```
- Der `scan`-Lauf (Erkennen stiller Korrekturen) wird automatisch beim
  `SessionStart` aus dem Banner heraus ausgeführt — ein separater Hook dafür ist
  nicht nötig. Für Cron kannst du ihn auch direkt aufrufen:
  `python3 integrations/claude_code/correction_synapse.py --scan`.
