---
name: project-widget-api
description: Überblick zum Widget-API-Dienst — Verantwortlichkeiten, Endpunkte, offene Punkte
metadata:
  node_type: memory
  type: project
  confidence: 0.8
  created: 2026-01-02
  last_verified: 2026-01-20
---
# Projekt: Widget-API

Die Widget-API ist der zentrale Dienst zum Anlegen, Lesen und Aktualisieren von
Widgets. Sie sitzt hinter dem Rate-Limit-Gateway und nutzt den gemeinsamen Cache.

## Endpunkte
Die vollständige Liste steht in [[reference-widget-api-endpoints]]. Wichtig sind
vor allem die Paginierungs-Routen ([[reference-pagination-cursors]]) und der
Webhook-Callback ([[project-webhook-delivery]]).

## Offene Punkte
- Cache-Invalidierung an allen Schreibpfaden prüfen ([[feedback-caching-lessons]]).
- Retry-Politik der Clients vereinheitlichen ([[feedback-retry-backoff]]).
- Konfiguration über das neue Schema laden ([[reference-config-schema]]).

## Deploy
Der Dienst wird über die Deploy-Pipeline ausgerollt ([[project-deploy-pipeline]]).
