---
name: reference-config-schema
description: Aufbau des Konfigurations-Schemas — Quellen, Vorrang und Validierung
metadata:
  node_type: memory
  type: reference
  confidence: 0.87
  created: 2026-01-11
  last_verified: 2026-01-20
---
# Referenz: Konfigurations-Schema

Konfiguration wird aus drei Quellen aufgelöst, in dieser Reihenfolge des Vorrangs:
Umgebungsvariable, Profil-Datei, eingebauter Default. Genau dieses Muster nutzt
auch das markmem-Paket selbst.

- Jeder Wert hat einen Default — fehlt etwas, bricht nichts (fail-open).
- Die Rate-Limits werden hierüber gesetzt ([[reference-rate-limit-policy]]).
- Das Widget-API-Projekt lädt seine Einstellungen daraus ([[project-widget-api]]).

Validierung beim Start; ungültige Werte werden geloggt und auf den Default
zurückgesetzt ([[feedback-logging-correlation]]).
