# Samvev for Home Assistant

Samvev is a custom Home Assistant integration that connects Home Assistant to a
Samvev server. This repository contains the **Home Assistant adapter only**. It does
not contain Samvev Core, AI interpretation, family data, rules, relevance decisions,
or notification policy.

Version 0.1 provides a UI config flow, a small asynchronous API client, two generic
actions, and a deliberately small status projection. The server API is provisional
and isolated in `custom_components/samvev/api.py` so the contract can evolve without
spreading HTTP details through the integration.

## Architecture

```text
selected HA state ─┐
manual automation ─┼─> Samvev HA adapter ─> Samvev API/Core
action call ───────┘                         │
                                            └─> structured context projection
                                                      │
                                                      └─> HA sensors
```

Home Assistant is one optional input/output adapter alongside future Homey, mobile,
web, and other adapters. The integration never scans or exports the complete Home
Assistant state machine. `samvev.event` includes local state only when entity IDs are
explicitly selected, and then includes only `entity_id`, state, and `last_changed`.

The five-minute status poll reads a projection already computed by Samvev. It must
not cause AI processing. Interpretation should happen in Samvev Core when source
information changes, with structured results stored for cheap reads.

See [architecture details](docs/architecture.md) and the
[provisional API contract](docs/api-contract.md).

## Installation

### Custom component

1. Copy `custom_components/samvev` into the Home Assistant configuration directory
   as `custom_components/samvev`.
2. Restart Home Assistant once after the initial installation.
3. Open **Settings → Devices & services → Add integration**, search for **Samvev**,
   and enter the server URL and API token.

Updates to a loaded config entry can be applied with the normal Home Assistant
reload control. Removing the integration under **Devices & services** removes its
entities; delete the copied directory separately if uninstalling manually.

### HACS custom repository

The repository layout and root `hacs.json` are ready for use as an Integration-type
custom repository once this project has a public GitHub remote. Default-store
submission, branding, and releases are intentionally out of scope for v0.1.

### Development

Python 3.13.2 or newer is required. With [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/samvev
```

Tests run against a real Home Assistant test harness and mocked Samvev HTTP
responses; no backend or credentials are needed. More detail is in
[the development guide](docs/development.md).

## Configuration

- **Server URL**: the HTTP(S) base URL for Samvev. Deployment paths are supported.
  URLs containing user info, query parameters, or fragments are rejected.
- **API token**: sent as a Bearer token. It is stored in the Home Assistant config
  entry and redacted from diagnostics.

The config flow verifies `GET /api/v1/health` and prevents duplicate configuration
of the same reported Samvev instance.

## Actions

### `samvev.ask`

Sends an explicit query to Samvev and returns response data.

```yaml
action: samvev.ask
data:
  prompt: "What needs attention tomorrow?"
  context:
    channel: home
response_variable: samvev_answer
```

Fields: required `prompt`, optional structured `context`, and optional
`config_entry_id`. The connection must be selected when more than one is loaded.

### `samvev.event`

Sends a generic structured event. This example shares the current condition of one
explicitly selected entity:

```yaml
action: samvev.event
data:
  event_type: household.context_changed
  data:
    reason: scheduled_check
  entity_ids:
    - weather.home
```

Fields: required `event_type`, optional object `data`, optional `entity_ids`, and
optional `config_entry_id`. Entity attributes are not implicitly exported. Callers
can put deliberately selected richer values into `data`, for example using HA
templates.

There is no `samvev.notify` action in v0.1. Home Assistant's existing notification
actions are the clean output mechanism for HA-local delivery; a future inbound
Samvev action/event contract should be designed with Samvev Core rather than adding
a second notification abstraction prematurely.

## Entities

- **API status**: current status from the structured context projection; diagnostic.
- **Next attention**: summary and structured `id`, `summary`, `due_at`, and `kind`
  attributes when Samvev has decided something deserves attention.
- **Attention count**: count when the backend provides it; unknown otherwise.

The optional context endpoint may return sparse fields. If it is not implemented,
the adapter remains connected and attention values remain unknown. Network failures
mark coordinator-backed entities unavailable until polling recovers.

## API contract

The adapter currently uses:

- `GET /api/v1/health`
- `GET /api/v1/context` (optional for an early backend)
- `POST /api/v1/ask`
- `POST /api/v1/events`

Payloads, response shapes, status handling, and compatibility behavior are specified
in [docs/api-contract.md](docs/api-contract.md). HTTP requests exist only in the
client module.

## Security and privacy

- No credentials, home-network addresses, people, schools, or entity IDs are
  hardcoded.
- Tokens are password fields, never included in client representations or normal
  logs, and redacted from diagnostics.
- Diagnostics omit attention IDs and text because these can contain personal data.
- Local context is opt-in per action. There is no whole-state export or automatic
  discovery-based forwarding.
- TLS (`https`) should be used outside a trusted local development environment.
- Samvev Core, not this adapter, decides whether information is relevant enough to
  notify someone.

## Planned later

Potential follow-up work includes reauthentication/reconfiguration UI, a stable
server capability handshake, server-to-HA event delivery, Assist integration, and
official branding/release automation. Calendar interpretation, family/person models,
AI calls, rules, memories, notification relevance, scraping, and other adapters
belong in Samvev Core or their own repositories.

## License

MIT. See [LICENSE](LICENSE).
