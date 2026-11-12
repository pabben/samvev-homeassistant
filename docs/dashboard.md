# Dashboard and Shelly Wall Display XL

The adapter provides ordinary HA entities; the dashboard is built in HA. It does
not embed the Samvev website and does not require PR #25.

1. Add the integration with connection name **Samvev HA**.
2. Find its actual entities under **Devices & services → Samvev → Entities**.
3. Create a dashboard, take control if required, and paste
   [examples/dashboard.yaml](../examples/dashboard.yaml) into its raw configuration.
4. Replace entity IDs if HA has assigned a suffix or you used another name.
5. Add each explicitly shared imported calendar as another calendar/agenda card,
   or combine them in one of the optional calendar cards below.

| Example entity | Purpose |
|---|---|
| `todo.samvev_ha_groceries` | Standard checkbox/add/edit/delete grocery board |
| `sensor.samvev_ha_messages` | Count state and `messages` array of all active rows |
| `calendar.samvev_ha_samvev` | Native events; full standard calendar interval API |
| `sensor.samvev_ha_connection_status` | Connected/disconnected, polling interval, last success |
| `sensor.samvev_ha_last_success` | Timestamp of last successful snapshot |

The default dashboard uses native to-do, Markdown and entities cards. Its
calendar Markdown reads `calendar.*`'s `agenda` attribute, two complete day groups
in the household timezone. This handles a Sunday/Monday boundary, simultaneous
appointments, overnight overlap and all-day entries without a custom card. The
standard calendar entity still exposes every event in an explicitly requested
interval; the two-day display attribute does not limit calendar APIs.

The two-day projection includes earlier appointments today. It shows unavailable
or stale content explicitly. Imported calendars whose synchronized window does
not cover both days become unavailable rather than claiming a complete empty
plan. The `source_freshness`, `last_source_sync`, `source_error` and
`last_complete_window` calendar attributes distinguish source sync problems from
an otherwise healthy HA connection. Samvev import intervals/provider caches can
add delay beyond the HA polling interval.

The example labels are Norwegian; change them in HA for other display languages.
Integration-owned GUI/entity/action text is localized in `en` and `nb`. Keep the
HA display timezone aligned with the household timezone for formatted clock times.
The server always preserves aware event instants and civil all-day dates.

## Optional existing calendar cards

[Calendar Card Pro](https://github.com/alexpfau/calendar-card-pro) and
[Week Planner Card](https://github.com/FamousWolf/week-planner-card) were inspected
against their upstream configuration examples. Install either through HACS
separately and refresh the frontend/resources as that project's guide describes.
Neither is bundled or required by this integration.

Replace the day-plan Markdown card with
[calendar-card-pro.yaml](../examples/calendar-card-pro.yaml) or
[week-planner.yaml](../examples/week-planner.yaml). Both examples request two days;
add your native and selected imported `calendar.*` entities to the relevant list.
Calendar Card Pro uses `entities`/`days_to_show`; Week Planner uses
`calendars`/`days`/`startingDay`. Do not mix their configuration keys. Native HA
calendar cards and automations remain supported independently.

## Display checks

Sections stack vertically on a narrow display and use three columns at 1280px.
Messages wrap fully, retain separate authors and importance, and remain a list;
no message text is stored in the truncated sensor state. The built-in to-do card
provides its normal touch/keyboard controls. Detailed evidence and screenshots are
in [validation.md](validation.md).

Browser checks at 1280×752 and 390×844 are not physical Shelly verification. The
remaining device check is the actual Shelly firmware's HA dashboard path, scrolling,
touch operation, sustained performance and login/session persistence. No HA public
exposure or networking/security changes are required by this adapter.
