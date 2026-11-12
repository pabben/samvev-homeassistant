# Installation and connection management

## Compatible server

Install the companion Samvev backend change implementing HA bridge v1 first.
The reference baseline is `feat/m3-family-hub` at `a298203`; the bridge change is
on `feat/native-ha-bridge`, commit `c457a824d46c8624e922346de637e4e2633c1329`,
and adds migration `047_home_assistant_bridge.sql`.
See the [backend protocol](https://github.com/pabben/samvev/blob/feat/native-ha-bridge/docs/implementation/HA_BRIDGE_API.md).
This development work does not deploy it into an existing installation. Follow
Samvev's backup/migration procedure when you separately authorize an upgrade.
PR #25's iframe/display embedding is independent and is not required.

Backend migration 047 extends allowed integration capabilities, adds explicit
sharing and durable operation receipts, and supports an integration message/board
actor. Existing credential meanings and earlier migration checksums are retained.
The native calendar uses Samvev's existing item model, not a parallel calendar
server. For rollback, revoke the new connection and disable/remove the HA adapter;
retain the additive schema and authored data. Do not run a destructive down
migration or restore a database over newer writes. A full schema rollback needs
a separately verified backup and the normal Samvev recovery procedure.

## Install the custom component

Supported minimum: Home Assistant 2026.2.3 / Python 3.13.2. Tests were executed on
HA 2026.2.3, not every later HA version. Integration version: 0.2.0.

For PR review, download the `feat/native-ha-entities` branch archive and copy only
`custom_components/samvev` into your HA configuration's `custom_components` folder.
Restart HA. After the PR is merged, HACS's **Custom repositories** can install
`pabben/samvev-homeassistant` with category **Integration**. The project is not
represented as approved in HACS's default selection. A Git branch under review
does not change what HACS downloads from the default branch.

## Create a machine credential

Run [scripts/provision_connection.py](../scripts/provision_connection.py) on a
trusted machine. It needs Python's standard library, not the HA development venv.
The manager password is entered using a non-echoing prompt. The temporary manager
session is logged out; the adapter stores only the separately revocable bearer.
The command refuses redirects and will not overwrite an existing output file.
If sharing/file setup fails, it attempts to revoke the incomplete new connection.

Inspect available IDs without creating a connection:

```bash
python scripts/provision_connection.py \
  --url https://samvev.example.invalid --email manager@example.invalid --inspect
```

The output contains household/person/source IDs and names required for selection,
not birthdays, account emails, permissions or private content. Choose the existing
household and sources. Samvev currently offers one native shopping board,
`groceries`; there are no extra named lists to create in this integration.

Example explicit selection:

```bash
python scripts/provision_connection.py \
  --url https://samvev.example.invalid --email manager@example.invalid \
  --name 'Samvev HA' --household HOUSEHOLD_UUID \
  --share-groceries --write-groceries \
  --messages --write-messages --calendar --write-calendar \
  --share-household --calendar-source SOURCE_UUID \
  --output /private/samvev-ha-connection.json
```

Omit `--calendar-source` if only native Samvev appointments are wanted. Repeat it
for each existing imported source. Omit all `--write-*` options for read-only
access. Repeat `--person PERSON_UUID` to permit content explicitly readable by
those people; this is independent of whom an appointment concerns. Omit
`--share-household` if household-addressed content should not be exported.
Imported source reader ACLs still apply. Both read and write capabilities are
required by mutation endpoints returning an authoritative resource.

The new JSON file is created with mode 0600. Use its `base_url` and `api_token`
in HA's **Settings → Devices & services → Add integration → Samvev** form.
Configure the final base URL as reachable **from HA**. HTTPS validates normal
certificates; HTTP is intended for a trusted local network/development fixture.
The token authenticates the installation/connection identity and versioned bridge,
not a public health endpoint. No callback from Samvev to HA is needed.

## Sharing and revocation

The provisioning command creates server-side sharing through existing manager
login/CSRF authorization. It does not let HA choose its own permissions. Server
administration paths are:

- `GET /api/v1/households/:householdId/integrations` — connection/credential metadata.
- `GET/PATCH …/integrations/:connectionId/ha-sharing` — inspect/replace the complete
  export policy with its `expectedRevision`.
- `POST …/integrations/:connectionId/credentials` — issue a replacement credential
  with connection `expectedRevision` and explicitly selected capabilities.
- `POST …/integrations/:connectionId/credentials/:credentialId/revoke` — revoke
  the old credential with credential `expectedRevision`.
- `POST …/integrations/:connectionId/revoke` — revoke the entire stable connection
  with connection `expectedRevision`.

These are manager APIs, not bearer APIs. Use Samvev's existing authenticated
administration tooling; do not put manager sessions in HA. See the full
[sharing payload and credential API](https://github.com/pabben/samvev/blob/feat/native-ha-bridge/docs/implementation/HA_BRIDGE_API.md)
and [M3 credential administration](https://github.com/pabben/samvev/blob/feat/native-ha-bridge/docs/implementation/M3_API.md).
For example, removing `groceries` from `listIds` stops its disclosure/writes.
An empty household/person audience stops messages/calendar disclosure. Imported
sources need both source selection and current reader permission. Server revokes
access immediately; HA clears displayed protected state on the next request,
normally within its 30-second poll schedule. Lost credentials initiate HA reauth.

## Reconfigure, rotate, unload and remove

Use the integration entry's **Reconfigure** menu to change the server URL or token.
The handshake must return the same stable installation and connection identity;
use a new integration entry for a different connection. Reauthentication accepts
a replacement token for the same connection. Normal reload stops old listeners,
timers/background tasks and reinstalls entity platforms.

Removing the HA config entry unloads its platforms and deletes its local operation
key store. It does **not** revoke the server credential or delete Samvev content:
revoke the connection in Samvev as a separate deliberate action. This preserves
server-authored grocery items/messages/events. Manual uninstall additionally
removes the copied component folder after the config entry has been removed.

HA users able to access these entities can see the content shared with this
connection. HA dashboard visibility is not an independent Samvev person grant.
Use separate narrowly shared connections/HA access policies when audiences differ.
