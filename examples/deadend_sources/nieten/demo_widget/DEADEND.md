# Demo-Widget-Sync — Dead-End

Plattform: synthetisches Demo-Szenario (kein reales System)

Kurz: Der Versuch, Widgets über einen direkten Datenbank-Sync statt über die
Widget-API zu spiegeln, war eine Sackgasse. Hier festgehalten, damit derselbe
Ansatz nicht erneut vorgeschlagen wird.

## Verdikt

Bestätigt negativ. Der direkte DB-Sync umging die Cache-Invalidierung und die
Webhook-Zustellung der Widget-API komplett. Folge: doppelte Stale-Einträge und
verpasste Webhooks. Der Ansatz ist in diesem Kontext tot.

## Re-Approach

Nur sinnvoll, wenn die Widget-API eine offizielle Bulk-Import-Route bekommt, die
Cache-Invalidierung und Webhook-Versand mit auslöst. Ohne diese Route nicht
erneut versuchen.

## Lehre

Schreibpfade niemals an der API vorbeiführen — sonst gehen Cache-Invalidierung
und Zustell-Garantien verloren. Ein Sync ohne API-Semantik ist kein Sync.
