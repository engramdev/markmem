---
name: feedback-caching-lessons
description: Lehren zum Cache-Verhalten der Widget-API — Stale-Keys und Invalidierung sauber halten
metadata:
  node_type: memory
  type: feedback
  confidence: 0.88
  created: 2026-01-04
  last_verified: 2026-01-18
---
# Caching-Lehren (Widget-API)

Der Cache vor der Widget-API hat uns zweimal mit veralteten Einträgen erwischt.
Caching klingt simpel, ist aber die häufigste Stale-Falle.
Kernlehre: jeder Schreibpfad MUSS den zugehörigen Cache-Key invalidieren, sonst
liefert ein späterer Read einen Stale-Wert. Das ist dieselbe Klasse Fehler wie
im Deploy-Pipeline-Vorfall, nur an anderer Stelle.

- Key-Schema explizit dokumentieren (siehe [[reference-widget-api-endpoints]]).
- TTL kurz halten, wenn die zugrundeliegenden Daten häufig wechseln.
- Bei jeder Invalidierung loggen, damit man die Ursache später nachvollziehen kann
  ([[feedback-logging-correlation]]).

Verwandt: die Pagination-Cursor cachen wir bewusst NICHT, weil sie kurzlebig sind
([[reference-pagination-cursors]]).
