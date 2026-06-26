---
name: feedback-retry-backoff
description: Lehre zu Retry mit exponentiellem Backoff und Jitter gegen Thundering-Herd
metadata:
  node_type: memory
  type: feedback
  confidence: 0.84
  created: 2026-01-09
  last_verified: 2026-01-18
---
# Lehre: Retry mit Backoff

Naive Sofort-Retries gegen die Widget-API ([[project-widget-api]]) führten beim
Ausfall zu einem Thundering-Herd: alle Clients schlugen gleichzeitig wieder zu.

Kernlehre: jeder Retry braucht exponentielles Backoff PLUS Jitter, sonst
synchronisieren sich die Clients. Außerdem ein Limit der Versuche und Respekt vor
dem Rate-Limit ([[reference-rate-limit-policy]]).

- Backoff: base 200ms, Faktor 2, Jitter ±30%.
- Nach 5 Versuchen aufgeben und sauber loggen ([[feedback-logging-correlation]]).
- Idempotente Requests sind Voraussetzung für sicheres Retry.
