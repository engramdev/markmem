# Surprises Inbox (Demo)

> Synthetische Beispiel-Surprises. Format: `## <ts> [session] tags`, dann
> `cwd:` und ein `>`-Zitat. Triage via surprise_triage.py.

## 2026-01-22 09:14:03 [demo-session-1] correction
cwd: `/projects/widget-api`
> Schreibende Endpunkte müssen den Listen-Cache invalidieren, sonst liefert der nächste GET einen veralteten Widget-Eintrag.

## 2026-01-22 11:02:47 [demo-session-1] omission
cwd: `/projects/deploy-pipeline`
> Das Rollback wurde nie im Staging geprobt — nur das Forward-Deploy. Beim echten Rollback fehlten kompatible Migrationen.

## 2026-01-23 14:33:10 [demo-session-2] anti-pattern
cwd: `/projects/widget-api`
> Sofortige Retries ohne Backoff erzeugten beim Ausfall einen Thundering-Herd; alle Clients schlugen synchron wieder zu.

## 2026-01-23 16:20:55 [demo-session-2] positive-confirmation
cwd: `/projects/widget-api`
> Pagination funktioniert wie erwartet, Cursor bleibt stabil bei gleichzeitigen Einfügungen.
