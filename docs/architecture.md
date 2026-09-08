# Architecture

## Boundary

This integration is a thin adapter between Home Assistant and an independently
deployable Samvev API/Core. Samvev Core owns domain state and decisions. The adapter
owns only Home Assistant lifecycle, entity projection, action validation, explicit
state snapshots, and HTTP transport adaptation.

```text
Home Assistant ─┐
Homey ──────────┤
Mobile app ─────┼──> Samvev API/Core
Web ────────────┤
Other sources ──┘

Samvev API/Core ──> Home Assistant / Homey / app / web / other channels
```

No code in this repository models a family, interprets a schedule, invokes an LLM,
chooses notification recipients, or decides that an attention item is relevant.

## Component map

- `api.py`: HA-independent async HTTP client and response models. This is the only
  module that knows paths, authentication headers, and wire shapes.
- `config_flow.py`: collects the base URL/token, validates health, and identifies a
  server instance.
- `coordinator.py`: polls only the small precomputed context projection every five
  minutes. Equal responses do not trigger entity writes.
- `sensor.py`: maps the projection into three entities. Missing optional API fields
  become unknown values rather than setup failures.
- `services.py`: implements `ask`, `event`, connection selection, and minimal
  explicitly requested entity snapshots.
- `diagnostics.py`: exports operational state while removing credentials and
  attention content.
- `runtime.py`: typed client/coordinator ownership for `ConfigEntry.runtime_data`.

## Data flows

### Setup and polling

1. Config flow calls `health` before persisting an entry. Authentication failures
   later start a token replacement flow that validates identity and reloads the entry.
2. Config-entry setup calls `health` again so startup failures use HA retry/auth
   semantics.
3. The coordinator reads `context`; it never asks Core to interpret source data.
4. Sensors expose the returned projection and become unavailable on update failure.

`GET context` returning 404 is a temporary compatibility mode: status is connected,
while attention values are unknown. Other invalid responses fail the update.

### Outbound actions

`ask` sends a user-initiated prompt and optional explicit context. `event` sends an
event type and object payload. When `entity_ids` are supplied, the adapter adds only
the selected entities' IDs, current state strings, and timestamps. It neither
subscribes to all state changes nor forwards entity attributes.

## Lifecycle and ownership

Integration actions are process-level and registered from `async_setup`, as required
by current HA practice. Each config entry owns a client and coordinator through typed
`runtime_data`. Sensor platforms are forwarded during setup and unloaded through the
config-entry manager. HA owns the shared `aiohttp` session; the adapter does not close
it.

## Cost model

Polling reads cached structured state. Routine HA events cause no API request unless
an automation explicitly invokes `samvev.event`. AI usage, if any, is a Samvev Core
implementation choice and should normally occur only when source information changes.

## Deliberate non-features

- no backend, rule engine, scheduler, or persistent family/context store
- no automatic entity discovery/export
- no schedule or weather interpretation
- no HA-specific notification policy
- no Homey/mobile/web implementation
