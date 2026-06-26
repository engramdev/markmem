---
name: reference-metrics-observability
description: Welche Metriken wir erfassen — RED-Methode für Dienste der Widget-API
metadata:
  node_type: memory
  type: reference
  confidence: 0.82
  created: 2026-01-19
  last_verified: 2026-01-24
---
# Referenz: Metriken & Beobachtbarkeit

Für jeden Dienst erfassen wir nach der RED-Methode: Rate, Errors, Duration.

- Rate: Anfragen pro Sekunde, auch verworfene durch das Rate-Limit
  ([[reference-rate-limit-policy]]).
- Errors: Fehlerquote, getrennt nach Client- und Server-Fehlern.
- Duration: Latenz-Histogramm pro Endpunkt ([[reference-widget-api-endpoints]]).

Metriken ergänzen die strukturierten Logs ([[feedback-logging-correlation]]) und
fließen in Alarme ein. Dashboards zeigen den Zustand der Widget-API
([[project-widget-api]]).
