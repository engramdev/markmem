---
name: feedback-error-handling
description: Lehre zur Fehlerbehandlung — klare Fehlertypen statt verschluckter Ausnahmen
metadata:
  node_type: memory
  type: feedback
  confidence: 0.86
  created: 2026-01-21
  last_verified: 2026-01-25
---
# Lehre: Fehlerbehandlung

Verschluckte Ausnahmen in der Widget-API ([[project-widget-api]]) verbargen einen
echten Datenfehler über Tage. Ein leeres `except` ist eine Falle.

Kernlehre: Fehler explizit typisieren und an der richtigen Stelle behandeln; nur
fail-open, wo ein Default wirklich sicher ist (wie beim Konfig-Schema,
[[reference-config-schema]]).

- Erwartete Fehler liefern saubere Statuscodes, keine 500er
  ([[reference-widget-api-endpoints]]).
- Unerwartete Fehler werden mit Korrelations-ID geloggt
  ([[feedback-logging-correlation]]) und lösen einen Alarm aus
  ([[reference-metrics-observability]]).
- Retries nur bei wirklich transienten Fehlern ([[feedback-retry-backoff]]).
