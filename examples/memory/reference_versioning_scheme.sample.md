---
name: reference-versioning-scheme
description: Unser SemVer-naher Versionierungs-Ansatz für API und Migrationen
metadata:
  node_type: memory
  type: reference
  confidence: 0.86
  created: 2026-01-07
  last_verified: 2026-01-20
---
# Referenz: Versionierungs-Schema

Wir versionieren nach `MAJOR.MINOR.PATCH`. Breaking Changes erhöhen MAJOR, neue
abwärtskompatible Felder MINOR, Fixes PATCH.

- Die API trägt die MAJOR-Version im Pfad (`/v1/widgets`).
- Migrationen werden an eine MINOR-Version gebunden und müssen additiv sein
  ([[feedback-deploy-rollback]]).
- Das Staging-Gate prüft die Versionierung der Deploy-Pipeline
  ([[project-deploy-pipeline]]).

Clients lesen die Version aus dem `Api-Version`-Header.
