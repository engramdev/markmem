---
name: project-deploy-pipeline
description: Aufbau der Deploy-Pipeline — Stufen, Gates und Rollback-Strategie
metadata:
  node_type: memory
  type: project
  confidence: 0.82
  created: 2026-01-06
  last_verified: 2026-01-21
---
# Projekt: Deploy-Pipeline

Die Deploy-Pipeline rollt alle Dienste aus, inklusive der Widget-API
([[project-widget-api]]). Sie besteht aus vier Stufen: Build, Test, Staging,
Produktion. Jede Stufe ist ein Gate.

## Gates
- Build: Lint + Unit-Tests müssen grün sein.
- Staging: Smoke-Test gegen die Versionierung ([[reference-versioning-scheme]]).
- Produktion: manuelle Freigabe.

## Lehren
Ein fehlgeschlagenes Rollback hat uns einen Vorfall beschert — die Lehre steht in
[[feedback-deploy-rollback]]. Logging mit Korrelation hilft bei der Diagnose
([[feedback-logging-correlation]]).
