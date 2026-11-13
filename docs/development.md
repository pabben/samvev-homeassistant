# Development and actual-server verification

The adapter targets HA2026.2.3+ and Python3.13.2+, with dependencies pinned in
`uv.lock`. From this repository:

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/samvev
```

The normal suite loads actual HA config entries/platforms/action dispatch, with
synthetic HTTP responses. It checks GUI/auth/lifecycle, bounded transport, stable
IDs, revisions, durable retry metadata, network failure, privacy clearing, source
restrictions, messages/expiry, dates/DST and exact two-day dashboard attributes.
Mocked transport tests alone do not prove that Samvev implements the protocol.

## Real Samvev ↔ HA roundtrip

Use an isolated checkout of the companion Samvev branch `feat/native-ha-bridge`.
Its `tests/ha-bridge/compose.yaml` creates a separate ephemeral test database and
localhost-only API with synthetic household data. It does not use live volumes,
credentials or data. The test server refuses any database URL except the exact
synthetic test database. **Starting/restarting it resets that synthetic fixture.**

From that Samvev checkout:

```bash
docker compose -p samvev-m1 -f tests/ha-bridge/compose.yaml build ha-bridge-api
docker compose -p samvev-m1 -f tests/ha-bridge/compose.yaml up -d ha-bridge-api
```

Wait for `/api/v1/health` on `http://127.0.0.1:4193` to return200 and
`isolated_ha_fixture_ready` in that service's log. Back in this HA repository:

```bash
SAMVEV_REAL_URL=http://127.0.0.1:4193 uv run pytest tests/test_roundtrip.py --no-cov
```

The tests reject any other server URL. They use real HA entities/actions and a
real Samvev HTTP client; no backend transport is mocked. They verify:

- Existing Samvev grocery → HA checkbox/rename/reopen/delete → browser API readback;
  repeated additions deduplicated and concurrent stale edits visibly rejected.
- Member and HA messages simultaneously visible, HA connection authorship,
  updates/withdrawals read back from both projections.
- Standard HA event creation, DST and all-day reads, Samvev Home visibility,
  edit/move/cancellation through actual server code.
- Reload, narrower sharing and credential revocation remove protected state.
- The documented provisioning command creates exactly selected capabilities and
  a new mode0600 secret file using the actual manager API.

A separate HA harness test proves the30-second automatic polling timer. Actual
browser/update measurements, when executed, are recorded in `validation.md`.

The Samvev backend's own integration suite covers imported recurrence/cancellation,
251 simultaneous/overlapping occurrences, source windows/freshness, actual foreign
household IDs, replacement/revoked credentials, full-audience authorization,
receipt replay under changed grants, write-only denial and existing regressions.

Clean up **only these isolated service names** afterwards:

```bash
docker compose -p samvev-m1 -f tests/ha-bridge/compose.yaml rm --stop --force ha-bridge-api ha-bridge-check ha-bridge-db
docker network rm samvev-m1-ha-bridge-isolated
```

Do not use `down`, `--remove-orphans` or broad prune against the shared project:
other services can use that Compose project name. The isolated test DB is tmpfs;
its data disappears when its test container is removed.
