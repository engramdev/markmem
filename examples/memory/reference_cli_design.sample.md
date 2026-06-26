---
name: reference-cli-design
description: Prinzipien für das CLI-Design unserer Tools — Flags, Exit-Codes, Ausgabe
metadata:
  node_type: memory
  type: reference
  confidence: 0.88
  created: 2026-01-14
  last_verified: 2026-01-22
---
# Referenz: CLI-Design

Unsere Kommandozeilen-Werkzeuge folgen einheitlichen Regeln, damit Skripte sie
verlässlich aufrufen können.

- Default ist immer der sichere Dry-Run; verändernde Aktionen brauchen `--apply`.
- Exit 0 bei Erfolg, 1 bei Fehler — für CI-Gates auswertbar.
- Maschinenlesbare Ausgabe per `--json`, menschenlesbar als Default.
- Jedes Tool liest seine Einstellungen aus dem Konfig-Schema
  ([[reference-config-schema]]).

Neue Mitwirkende lernen diese Konventionen im Onboarding
([[user-onboarding-notes]]). Fehlerausgaben werden strukturiert geloggt
([[feedback-logging-correlation]]).
