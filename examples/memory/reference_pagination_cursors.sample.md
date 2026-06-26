---
name: reference-pagination-cursors
description: Wie Cursor-Paginierung in der Widget-API funktioniert und warum nicht Offset
metadata:
  node_type: memory
  type: reference
  confidence: 0.85
  created: 2026-01-05
  last_verified: 2026-01-19
---
# Referenz: Cursor-Paginierung

Die Listen-Endpunkte nutzen Cursor-Paginierung statt Offset. Ein Cursor kodiert
die Position als opaken, base64-kodierten Schlüssel. Vorteil: stabile Ergebnisse
auch bei gleichzeitigen Einfügungen.

- Der Cursor ist kurzlebig und wird NICHT gecacht ([[feedback-caching-lessons]]).
- Clients geben den `next`-Cursor unverändert zurück.
- Ungültige Cursor liefern 400, kein 500.

Eingesetzt in den Endpunkten aus [[reference-widget-api-endpoints]] und im
allgemeinen Widget-API-Projekt ([[project-widget-api]]).
