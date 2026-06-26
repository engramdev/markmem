---
name: reference-widget-api-endpoints
description: Referenz aller Widget-API-Endpunkte mit Methode, Pfad und Cache-Verhalten
metadata:
  node_type: memory
  type: reference
  confidence: 0.9
  created: 2026-01-03
  last_verified: 2026-01-19
---
# Referenz: Widget-API-Endpunkte

| Methode | Pfad                | Cache | Notiz                          |
|---------|---------------------|-------|--------------------------------|
| GET     | /widgets            | ja    | Liste, paginiert (Cursor)      |
| GET     | /widgets/{id}       | ja    | Einzelnes Widget               |
| POST    | /widgets            | nein  | invalidiert Listen-Cache       |
| PATCH   | /widgets/{id}       | nein  | invalidiert Einzel- und Liste  |
| DELETE  | /widgets/{id}       | nein  | invalidiert Einzel- und Liste  |

Das Cache-Verhalten hängt eng an den Lehren in [[feedback-caching-lessons]].
Die Paginierung der Liste folgt dem Cursor-Modell aus
[[reference-pagination-cursors]]. Schreibende Endpunkte stoßen den
Webhook-Versand an ([[project-webhook-delivery]]).
