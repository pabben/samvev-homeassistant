# Native HA bridge protocol

Version: `schemaVersion: 1`, integration version 0.2.0. The canonical contract and
server enforcement live in [Samvev HA_BRIDGE_API.md](https://github.com/pabben/samvev/blob/feat/native-ha-bridge/docs/implementation/HA_BRIDGE_API.md).
Every request starts at the configured base URL plus `/api/v1/ha`, carries the
separate bearer credential and refuses redirects. Responses are size/time bounded.
The public `/health` endpoint does not validate authorization. The old local
adapter's provisional `/context`, `/ask` and `/events` protocol is replaced.

| Endpoint | Purpose |
|---|---|
| `GET /connection` | Authenticated schema, installation/connection identity, timezone, capabilities, grants |
| `GET /snapshot` | Complete explicitly shared grocery board, active messages and calendar descriptors |
| `POST /lists/groceries/items` | Add label and checked state |
| `PATCH, DELETE /lists/groceries/items/:id` | Revision-protected edit/check/reopen or deletion |
| `POST /messages` | Create as this connection, targeting only allowed recipients |
| `PATCH /messages/:id`, `POST /messages/:id/withdraw` | Edit/withdraw this connection's own message |
| `GET /calendars/:id/events?start=…&end=…` | All overlapping allowed events in the exact interval, up to 366 days |
| `POST /calendars/samvev/events` | Create an own Samvev event |
| `PATCH, DELETE /calendars/samvev/events/:id` | Edit/cancel own event using its observed revision |

JSON field names are camelCase. HA action input uses HA-style snake_case and
converts at the client boundary. Every mutation carries `requestKey`; edits and
deletes also carry `expectedRevision`. Do not regenerate the key after a timeout.
The coordinator persists hashes and keys before dispatch. Ambiguous attempts can
reuse their operation key after restart. Successfully acknowledged identical
button operations reuse a key for ten seconds to collapse repeated presses;
explicit keys can control intentional repeated additions. Pending data is key
metadata, not a second content store. Removing the config entry deletes this store.

A 409 triggers refresh and a visible conflict error. It never fetches a newer
revision merely to overwrite it. Calendar edits require an event revision already
observed by this entity; query the event first after a restart. Network errors
retain the previous safe projection as unavailable/stale; they never clear lists.
401/403 triggers authority refresh/reauth and removes protected data. Revocation
is enforced server-side immediately; an already rendered HA view learns of it
on its next request, normally the next 30-second poll. No polling adapter can erase
a screenshot or previously viewed content from somebody's memory.

Calendar all-day values are civil `YYYY-MM-DD` dates with exclusive end. Timed
events are timezone-aware ISO instants. Imported occurrences are expanded by
Samvev's existing provider importer; no independent recurrence engine is added to
HA. Moves, overrides and cancellations retain server identities/revisions.
Imported source windows and upstream cache delays still apply. Source freshness
is distinct from successful HA polling and is exposed in calendar attributes.
HA calendar exports are excluded from the Samvev HA importer to avoid feedback.

The existing `integration.items.read` capability continues to read only a
connection's own external items. It does not grant family data. Dedicated
`ha.groceries.read/write`, `ha.messages.read/write` and `ha.calendar.read/write`
capabilities combine with explicit server-side grants. Mutation endpoints require
both the corresponding read and write capability because their responses return
the authoritative resource. Write permission never implicitly creates read permission. A household grant permits
household-addressed content; selected people are **readers**, not inferred subjects.
Imported sources additionally require their explicit source IDs.

Messages preserve simultaneous entries and expire locally even before a later
poll. The sensor state is the count, with complete active messages in attributes.
HA does not acknowledge display rendering, reading, approval or task completion.
No XP/reward service is invoked. A HA dashboard user's identity is not mapped to a
Samvev person. The durable audit actor is the integration connection and credential.

Known model limits: one existing grocery board; grocery fields are label/checked
only; own calendar recurrence creation is unsupported; imported provider writes
are unsupported; HA can edit/withdraw only its own messages and calendar events.
