---
name: project-dependency-hygiene
description: Pflege der Abhängigkeiten — Pinning, Updates und Supply-Chain-Prüfung
metadata:
  node_type: memory
  type: project
  confidence: 0.77
  created: 2026-01-20
  last_verified: 2026-01-24
---
# Projekt: Abhängigkeits-Hygiene

Wir halten Abhängigkeiten schlank und nachvollziehbar.

## Regeln
- Versionen pinnen, Updates in kleinen Schritten ([[user-team-preferences]]).
- Jedes Update läuft durch das Test-Gate ([[feedback-testing-strategy]]).
- Neue Abhängigkeiten auf Lizenz und Pflege prüfen.

## Bezug zur Pipeline
Aktualisierungen werden über die Deploy-Pipeline ausgerollt
([[project-deploy-pipeline]]) und nach dem Versionierungs-Schema markiert
([[reference-versioning-scheme]]). Verdächtige Pakete werden niemals mit
Secrets gefüttert ([[feedback-secrets-hygiene]]).
