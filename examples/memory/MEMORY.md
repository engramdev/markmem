# Memory Index — Demo-Korpus (Widget-API)

> Synthetischer Demo-Index für markmem. Alles erfunden, keine echten Daten.
> Lese-Reihenfolge ist semantisch: oben die heißesten Karten, Details in
> MEMORY_DEEP.md und MEMORY_INFRA.md.

## Hot — am häufigsten gebraucht

- [Widget-API](project_widget_api.sample.md) — zentraler Dienst, Endpunkte + offene Punkte
- [Deploy-Pipeline](project_deploy_pipeline.sample.md) — Build/Test/Staging/Prod als Gates
- [Caching-Lehren](feedback_caching_lessons.sample.md) — Schreibpfad invalidiert Cache-Key
- [Logging mit Korrelation](feedback_logging_correlation.sample.md) — Korrelations-ID = schnellste Diagnose
- [Secrets-Hygiene](feedback_secrets_hygiene.sample.md) — nie in Code/Log/Cache
- [Retry mit Backoff](feedback_retry_backoff.sample.md) — exponentiell + Jitter gegen Herd
- [Team-Vorlieben](user_team_preferences.sample.md) — kurz, kleine Schritte, Tests dabei

## Regeln (immer beachten)

- Default ist Dry-Run; verändernde Aktionen brauchen ein explizites `--apply`.
- Keine Secrets in Code, Log oder Cache — beim Logging filtern.
- Jede Änderung kommt mit Tests; vor Code-Änderungen ein Branch.
- Fail-open nur, wo ein Default wirklich sicher ist (Konfig-Schema).
- Kurze, nachvollziehbare, rückbaubare Schritte bevorzugen.
