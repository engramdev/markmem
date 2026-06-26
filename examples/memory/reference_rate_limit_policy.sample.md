---
name: reference-rate-limit-policy
description: Rate-Limit-Politik des Gateways vor der Widget-API mit Token-Bucket
metadata:
  node_type: memory
  type: reference
  confidence: 0.83
  created: 2026-01-10
  last_verified: 2026-01-19
---
# Referenz: Rate-Limit-Politik

Das Gateway vor der Widget-API ([[project-widget-api]]) nutzt einen Token-Bucket
pro Client. Standard: 100 Anfragen pro Minute, Burst bis 20.

- Überschreitung liefert 429 mit `Retry-After`-Header.
- Clients sollen den Header respektieren statt blind zu wiederholen
  ([[feedback-retry-backoff]]).
- Die Grenzen sind pro Umgebung konfigurierbar ([[reference-config-schema]]).

Server zählen verworfene Anfragen und melden sie als Metrik
([[feedback-logging-correlation]]).
