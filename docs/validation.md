# Verification evidence — 2026-11-12

Backend reference: `c457a824d46c8624e922346de637e4e2633c1329`.

The main agent reviewed the implementation, ran actual-server roundtrips and
workspace checks, and inspected the rendered dashboard. Independent agents
reviewed requirements/security, corrected findings and reran the complete backend
suite. All data used for tests, provisioning and screenshots is synthetic.
No live household installation, production configuration or physical Shelly was
modified. No secret or private family data is included in this repository.

## Executed checks

| Check | Result |
|---|---|
| Full Samvev API suite in separate temporary PostgreSQL | **490 passed; 0 failed; 0 skipped** |
| HA integration suite, actual HA2026.2.3 harness | **74 passed; 3 opt-in real-server tests skipped in this command** |
| Those three real-server interoperability tests, run separately | **3 passed**, actual Samvev code + actual HA entities/actions, no mocked transport |
| HA branch coverage | **93.92%**, above the85% gate |
| Ruff check and formatting | Passed |
| Mypy | Passed,11 integration modules |
| Samvev complete workspace typecheck | Passed |
| Official HA action metadata schema | All3 message actions valid |
| en/nb action metadata | Complete matching action/field keys |
| Frozen dependency lock check | Passed |
| Packaged ZIP inspection |16 integration source/resource files, correct custom_components/samvev path, no bytecode/configuration |
| Git whitespace checks | Passed |
| Native dashboard in actual HA frontend | Light/dark,1280×752 and390×844; no horizontal overflow or JavaScript page errors in final capture |

The real-server tests perform grocery create/checkbox/rename/reopen/delete and
competing edits, simultaneous member/HA messages and lifecycle changes, native
calendar create/read/edit/move/cancel with DST/all-day semantics, imported complete
read-only calendar reads, reload, sharing removal, revocation and the documented
manager provisioning command. The normal suite independently verifies scheduled
30-second polling, outage recovery, unload cleanup, bounded transport, persistent
retry keys and denial of delayed calendar responses after changed sharing.

Backend tests also cover251 simultaneous imported occurrences without truncation,
source windows/freshness, provider-source restrictions, actual second-household
isolation, credential replacement/revocation, write-only denial, changed audiences
and authorization of old operation receipts. Existing calendar/Spond/temperature/
control behavior remains covered by the complete API regression suite.

Security findings were fixed before the final checks: write-only credentials
reading resource responses; calendar writes retaining removed recipients; replay
under changed audiences/display targets; unnecessary manager inspection fields;
and a delayed HA calendar response re-exposing content after narrower sharing.
The latter has explicit private-payload race regression tests.

## Actual update measurement

[actual-update.json](validation/actual-update.json) records one actual test on
HA2026.2.3: **24.219 seconds** from acknowledgement of a Samvev browser-API grocery
write to its automatic appearance in the HA dashboard, with a30-second poll
interval. Clicking its native to-do checkbox was then confirmed by actual Samvev
readback. No manual HA refresh was used for this measurement.

This is one measured sample, not a real-time claim or an upper latency guarantee.
HA scheduling, network outages and upstream calendar import/cache delays can add
time. Imported source freshness is separately visible in calendar attributes.

## Actual frontend screenshots

The final capture uses the official HA2026.2.3 container, actual custom integration,
actual Samvev API, native Lovelace cards, and only synthetic fixtures. The browser
viewports were1280×752 and390×844; images are full-page captures and can be taller.
[screenshots.json](validation/screenshots.json) records actual dimensions and SHA256.
[browser-checks.json](validation/browser-checks.json) records theme, geometry,
JavaScript page errors and horizontal-overflow checks.

| View | Light | Dark |
|---|---|---|
| Shelly XL browser viewport | [Screenshot](validation/screenshots/shelly-xl-light.png) | [Screenshot](validation/screenshots/shelly-xl-dark.png) |
| Narrow browser viewport | [Screenshot](validation/screenshots/narrow-light.png) | [Screenshot](validation/screenshots/narrow-dark.png) |

Both active messages, exact today/tomorrow plan, shopping controls and connection
status render. Long text wraps. Native checklist rows are56px high; checkbox
visuals are40px, as supplied by HA's built-in card. The screenshot checks do not
assert that every native control has a44px hit area. Adjust physical display
scaling after checking the actual firmware/browser and viewing distance.

## Deliberate limits and remaining checks

- Physical Shelly XL firmware, touch behavior, sustained performance and session
  persistence are **not tested**. Browser viewport checks do not substitute for them.
- Calendar Card Pro and Week Planner examples follow inspected upstream docs;
  these optional custom cards were not installed in the isolated frontend. The
  fully tested default dashboard uses native HA cards and needs neither.
- Real Google/Microsoft/Spond accounts and private household data were not used.
  Existing importer behavior was exercised with synthetic protocol/DB fixtures;
  external-provider consent/registration remains deployment-specific.
- Native recurrence creation and imported-provider writes are intentionally
  unsupported; HA feature flags and error behavior match that boundary.
- Installation through HACS's custom repository requires the implementation on
  its default branch; the unmerged review branch is manually installable or can
  be installed from the CI ZIP artifact. Default HACS selection is not claimed.
- Deployment and installation into an active household require a separate action.
  This change supplies code, tests and guides, not a production upgrade.
