# Architecture

Home Assistant initiates authenticated HTTP requests to existing Samvev. There
are no inbound HA webhooks and no extra runtime server in this repository.

`config_flow.py` validates schema and the stable installation/connection identity.
`api.py` owns bounded transport and protocol validation. `coordinator.py` polls an
authoritative snapshot every 30 seconds and persists idempotency key metadata for
ambiguous retries. Entity modules expose standard HA to-do/calendar APIs and
message/status sensors. `services.py` provides narrowly scoped message actions.

Samvev owns the existing grocery service, message lifecycle, provider calendar
import, native events, permissions, revisions and audit. Backend additions live in
a separate checkout/PR. The adapter neither copies these rules nor interprets text
with AI. Explicit server sharing is authoritative; HA cannot broaden a grant.

Entities cache their latest allowed projection for rendering. Network failures
make it unavailable/stale without inventing empty authoritative data. Revoked
authority clears current protected state. Service flags follow the snapshot's
actual permissions, and imported calendars remain read-only.

The dashboard is ordinary Lovelace YAML. Standard HA cards work without custom
frontend code; Calendar Card Pro and Week Planner Card are optional two-day views.
This architecture is separate from Samvev PR #25 and does not embed `/display`.
