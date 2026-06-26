---
name: feedback-secrets-hygiene
description: Lehre zur Secrets-Hygiene — niemals im Code, im Log oder im Cache
metadata:
  node_type: memory
  type: feedback
  confidence: 0.93
  created: 2026-01-18
  last_verified: 2026-01-24
---
# Lehre: Secrets-Hygiene

Ein versehentlich geloggtes Webhook-Secret zwang uns zu einer Rotation. Vermeidbar.

Kernlehre: Secrets gehören ausschließlich in den Secret-Store, nie in Code, Log
oder Cache. Beim Logging filtern, beim Embedding redigieren.

- Webhook-Secrets nur referenzieren, nie ausgeben ([[project-webhook-delivery]]).
- Strukturierte Logs durch einen Redaktions-Filter schicken
  ([[feedback-logging-correlation]]).
- Konfigurierte Geheimnisse aus dem Schema nur per Referenz laden
  ([[reference-config-schema]]).

Diese Regel ist Teil der Team-Vorlieben ([[user-team-preferences]]).
