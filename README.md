# Samvev for Home Assistant

A native custom integration connecting an existing [Samvev](https://github.com/pabben/samvev)
installation to Home Assistant. No extra server, iframe, AI engine or duplicate
family database is installed.

- **Shopping:** standard `todo` entity; add, rename, check, reopen and delete with
  Samvev's stable IDs, revisions and permissions. Samvev currently has one shared
  household grocery board; explicitly select that existing board.
- **Messages:** every active shared message, with author, audience, publication,
  expiry, importance and revision. Numeric sensor state; complete message rows in
  attributes. Actions create, edit and withdraw this connection's own messages.
- **Calendar:** standard calendar entities and full interval reads. Create,
  edit and cancel this connection's own Samvev events. Existing imported
  Google/Outlook/ICS/Spond/HA sources remain read-only and explicitly selected.
- **Connection:** GUI setup, reauthentication and URL/token reconfiguration;
  30-second polling, last-success status, recovery and durable retry keys.

Samvev remains authoritative for household membership, sharing, content and
business rules. A check mark never awards XP or parental approval. HA actions
are attributed to the named integration connection, **not** the HA dashboard user.

## Requirements and installation

Home Assistant **2026.2.3 or later**, Python 3.13.2 or later, and a Samvev server
implementing **HA bridge schema version 1** are required. This is a paired change:
older Samvev installations with only `/api/v1/integrations/items` are insufficient.
See the [upstream contract](https://github.com/pabben/samvev/blob/feat/native-ha-bridge/docs/implementation/HA_BRIDGE_API.md)
and [installation guide](docs/installation.md). The integration validates this
contract during setup instead of accepting an unauthenticated health check.

### HACS custom repository

After the implementation PR has been merged into this repository's default branch:

1. In HACS, open **Custom repositories**.
2. Add `https://github.com/pabben/samvev-homeassistant`, category **Integration**.
3. Download **Samvev** and restart HA.
4. Open **Settings → Devices & services → Add integration → Samvev**.
5. Enter the Samvev base URL and the separately issued integration bearer token.

This is a custom repository, not a claim of inclusion in HACS's default selection.
While reviewing the unmerged branch, use the manual installation below.

### Manual installation / PR review

Download the `feat/native-ha-entities` branch archive. Copy its
`custom_components/samvev` directory into `<HA config>/custom_components/samvev`
and restart HA. The result must be `<HA config>/custom_components/samvev/manifest.json`,
not an extra nested repository directory. Add the integration through the GUI.
Only copy the custom component; development scripts and backend code are not HA
runtime requirements.

## Explicit sharing

Issue a new revocable credential for HA. Do not paste an administrator session,
HA token, browser cookie or paired-display cookie into the config flow.

The supplied [provisioning command](scripts/provision_connection.py) uses a
short-lived Samvev manager login to select content and issue a bearer credential.
It revokes that temporary session afterwards; HA receives only the new credential.
For example, from a trusted machine with Python 3.13:

```bash
python scripts/provision_connection.py \
  --url https://samvev.example.invalid --email manager@example.invalid \
  --name 'Samvev HA' --share-groceries --write-groceries \
  --share-household --messages --write-messages --calendar --write-calendar \
  --output /private/samvev-ha-connection.json
```

Replace the example URL/email and choose a private, writable output directory.
The password is prompted without echo. The new file has mode 0600 and contains
`base_url` and `api_token` for HA setup. It is never printed or added to this repo.
Read-only access is obtained by omitting the respective `--write-*` switches.
`--inspect` lists available households, people and imported calendar source IDs
without creating a credential. Use `--household UUID` when needed, repeat
`--person UUID` to share person-reader content, and `--calendar-source UUID` to
select each imported calendar. Subject/person association alone does not grant
access. See [sharing and revocation](docs/installation.md#sharing-and-revocation).

## Dashboard

Use [examples/dashboard.yaml](examples/dashboard.yaml) as the raw configuration
of a new dashboard. It uses native to-do, Markdown, status and calendar cards.
Rename its entity IDs to those shown in your HA installation; the example assumes
a connection named **Samvev HA**. Its day-plan Markdown card reads a two-day projection from the standard calendar
entity, including every permitted overlapping appointment.

For a richer **today + tomorrow** view, replace the day-plan Markdown card with
[Calendar Card Pro](examples/calendar-card-pro.yaml), or
[Week Planner Card](examples/week-planner.yaml). Install the chosen card separately
through HACS. Both are optional: the integration's standard calendar entities work
with native cards, other cards and automations. See [dashboard setup](docs/dashboard.md).

## Actions

Normal HA `todo.add_item`, `todo.update_item`, `todo.remove_item`,
`calendar.get_events` and `calendar.create_event` work through the standard entities.
Calendar edit/delete are available through HA's calendar interface. Imported
calendars have no write feature flags. Native recurring creation is unsupported;
existing provider recurrence instances are read from Samvev's import projection.

```yaml
action: samvev.create_message
data:
  body: Husk syntetisk øvingsutstyr
  audience:
    household: true
    person_ids: []
  importance: attention
  expires_at: '2027-01-15T20:00:00+01:00'
  request_key: practice-reminder-2027-01-15
response_variable: created_message
```

`samvev.update_message` and `samvev.withdraw_message` take `message_id` and
optionally `expected_revision` and `request_key`. Updates may change body,
audience, importance, publication and expiry. Without an explicit revision they
use the last observed message revision. Stale changes fail and refresh; they are
never silently applied over somebody else's edit. Only this connection's own
messages are writable. Select `config_entry_id` when several connections are loaded.
Use a stable, non-secret request key for retries of one automation operation and
a new key for a new operation. No action creates rendered/read/acknowledged or
task-completion receipts. See [protocol and limitations](docs/api-contract.md).

## Verification and development

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/samvev
```

Tests use the real HA test harness. The separate
[roundtrip procedure](docs/development.md) runs this integration against actual
Samvev code and an isolated synthetic database; mock tests alone are not treated
as proof of backend interoperability. See [validation evidence](docs/validation.md)
for executed checks and remaining hardware limits.

No change is installed on a running household's HA or Samvev by these development
tests. Physical Shelly Wall Display XL validation is a separate check; browser
viewport tests do not establish firmware/browser compatibility.

MIT; see [LICENSE](LICENSE). Backend changes remain in the separate AGPL Samvev repo.
