# Development

## Environment

The validated development stack is Python 3.13.2+, Home Assistant 2026.2.3, pytest,
Ruff, and mypy. Install [uv](https://docs.astral.sh/uv/) and run:

```bash
uv sync
```

Some platforms need a C compiler when a Home Assistant transitive dependency has no
prebuilt wheel.

## Validation

Run the full local gate:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy custom_components/samvev
uv run pytest
```

The pytest plugin supplies a real Home Assistant runtime. `aioclient_mock` intercepts
all Samvev requests, so tests are deterministic and cannot contact a real server.

## Manual loading

For a Home Assistant development configuration, link or copy
`custom_components/samvev` into `<config>/custom_components/samvev`, restart once,
and add the integration from the UI. A tiny fixture server implementing the draft API
is preferable to bypassing the client during manual checks; no backend belongs in
this repository.

## Change rules

- Keep all wire-format knowledge in `api.py` and update `docs/api-contract.md` with
  contract changes.
- Keep domain decisions in Samvev Core. Adapter code may validate/translate but not
  infer relevance.
- Add an explicit selector and document every new piece of HA context sent out.
- Never log request headers, tokens, full config-entry data, or server response
  bodies.
- Add lifecycle, failure, action, and diagnostics tests for behavior changes.
