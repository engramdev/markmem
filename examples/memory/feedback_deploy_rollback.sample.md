---
name: feedback-deploy-rollback
description: Warum unser Rollback fehlschlug und wie wir die Deploy-Pipeline gehärtet haben
metadata:
  node_type: memory
  type: feedback
  confidence: 0.9
  created: 2026-01-08
  last_verified: 2026-01-21
---
# Lehre: Deploy-Rollback

Ein Rollback in der Deploy-Pipeline ([[project-deploy-pipeline]]) schlug fehl, weil
die alte Version inkompatible Migrationen voraussetzte. Ergebnis: 12 Minuten
Ausfall.

Kernlehre: Rollbacks müssen vorwärts- UND rückwärtskompatibel getestet werden,
sonst ist die Rollback-Sicherheit nur eine Annahme. Die Versionierung
([[reference-versioning-scheme]]) muss das erzwingen.

- Migrationen immer additiv, nie destruktiv im selben Release.
- Rollback im Staging-Gate proben, nicht nur das Forward-Deploy.
- Korrelations-IDs im Log erleichtern die Ursachenanalyse ([[feedback-logging-correlation]]).
