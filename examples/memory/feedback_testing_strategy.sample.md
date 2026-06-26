---
name: feedback-testing-strategy
description: Lehre zur Test-Strategie — schnelle Unit-Tests, wenige gezielte E2E-Tests
metadata:
  node_type: memory
  type: feedback
  confidence: 0.85
  created: 2026-01-17
  last_verified: 2026-01-23
---
# Lehre: Test-Strategie

Eine Phase mit nur End-to-End-Tests machte die Suite langsam und flaky. Umgekehrt
fing reines Unit-Testen Integrationsfehler nicht.

Kernlehre: viele schnelle Unit-Tests als Basis, eine schmale Schicht gezielter
End-to-End-Tests obendrauf. Genau das erzwingt das Build-Gate der Deploy-Pipeline
([[project-deploy-pipeline]]).

- Unit-Tests müssen deterministisch sein, kein Netzwerk.
- E2E nur für kritische Pfade wie Widget-Anlage ([[project-widget-api]]).
- Flaky Tests sofort markieren, nicht ignorieren ([[user-team-preferences]]).
