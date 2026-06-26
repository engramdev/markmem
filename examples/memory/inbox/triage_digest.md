# Triage Digest — candidate clusters (Demo)

Generated 2026-01-25 10:05:00 by surprise_triage.py.
3 candidates in 2 clusters. Approve in one pass via `/memory-review`.

Each cluster is a PROPOSED theme — not yet a memory. Human decides per cluster:
promote (write feedback_*.md) · edit · reject.

---

## Cluster 1 — cache / invalidieren / widget  (2 items)

- `2026-01-22 09:14:03` (/projects/widget-api)
  > Schreibende Endpunkte müssen den Listen-Cache invalidieren, sonst liefert der nächste GET einen veralteten Widget-Eintrag.
- `2026-01-23 16:20:55` (/projects/widget-api)
  > Pagination funktioniert wie erwartet, Cursor bleibt stabil bei gleichzeitigen Einfügungen.

## Cluster 2 — rollback / retry / backoff  (1 items)

- `2026-01-22 11:02:47` (/projects/deploy-pipeline)
  > Das Rollback wurde nie im Staging geprobt — nur das Forward-Deploy. Beim echten Rollback fehlten kompatible Migrationen.
