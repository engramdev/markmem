---
name: project-webhook-delivery
description: Zustellung ausgehender Webhooks mit Signatur, Retry und Dead-Letter
metadata:
  node_type: memory
  type: project
  confidence: 0.79
  created: 2026-01-13
  last_verified: 2026-01-21
---
# Projekt: Webhook-Zustellung

Schreibende Endpunkte der Widget-API ([[reference-widget-api-endpoints]]) stoßen
ausgehende Webhooks an. Empfänger registrieren eine URL und ein Secret.

## Zustellung
- Jede Nachricht ist signiert (HMAC über den Body).
- Fehlgeschlagene Zustellungen werden mit Backoff wiederholt
  ([[feedback-retry-backoff]]).
- Nach erschöpften Versuchen geht die Nachricht in eine Dead-Letter-Queue.

## Beobachtbarkeit
Jeder Versuch wird mit Korrelations-ID geloggt
([[feedback-logging-correlation]]). Die Empfänger-Konfiguration folgt dem
Schema aus [[reference-config-schema]].
