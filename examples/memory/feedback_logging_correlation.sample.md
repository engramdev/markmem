---
name: feedback-logging-correlation
description: Warum strukturierte Logs mit Korrelations-ID jede Diagnose beschleunigen
metadata:
  node_type: memory
  type: feedback
  confidence: 0.91
  created: 2026-01-12
  last_verified: 2026-01-22
---
# Lehre: Logging mit Korrelation

Bei jedem Vorfall — Cache-Stale, Deploy-Rollback, Retry-Sturm — war die schnellste
Diagnose immer dort, wo eine Korrelations-ID den Request durch alle Dienste
verfolgbar machte.

Kernlehre: strukturierte JSON-Logs mit einer durchgereichten Korrelations-ID sind
kein Luxus, sondern die Grundlage jeder Ursachenanalyse. Niemals Secrets oder PII
loggen.

- Korrelations-ID am Gateway erzeugen, an Widget-API und Webhook weiterreichen
  ([[project-widget-api]], [[project-webhook-delivery]]).
- Cache-Invalidierungen explizit loggen ([[feedback-caching-lessons]]).
- Log-Level pro Umgebung über die Konfiguration ([[reference-config-schema]]).
