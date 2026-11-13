# Samvev for Home Assistant

En integrasjon som kobler en eksisterende [Samvev](https://github.com/pabben/samvev)-installasjon
til Home Assistant. Du trenger ingen ekstra server, innbygging av nettsiden,
AI-motor eller ny familiedatabase.

- **Handleliste:** vanlig `todo`-entitet. Legg til, endre navn, kryss av, gjenåpne
  og slett varer med Samvevs stabile ID-er, revisjoner og rettigheter. Samvev har
  for øyeblikket én felles handleliste; denne må deles uttrykkelig.
- **Beskjeder:** alle aktive delte beskjeder, med avsender, målgruppe,
  publisering, utløp, viktighet og revisjon. Sensorens tilstand er et antall;
  hele beskjedlisten finnes i attributtene. Handlinger oppretter, endrer og
  trekker tilbake beskjeder som forbindelsen selv har opprettet.
- **Kalender:** vanlige kalenderentiteter med alle hendelser i et forespurt
  tidsrom. Opprett, endre og avlys egne Samvev-avtaler. Importerte Google-,
  Outlook-, ICS-, Spond- og HA-kalendere velges uttrykkelig og er skrivebeskyttet.
- **Tilkobling:** GUI-oppsett, ny autentisering, endring av adresse/nøkkel,
  automatisk henting hvert 30. sekund, status for siste vellykkede henting og
  håndtering av avbrudd og nye forsøk.

Samvev bestemmer personer, husstander, rettigheter, innhold og forretningsregler.
Avkryssing gir ingen foreldregodkjenning eller XP. Handlinger fra HA registreres
som den navngitte integrasjonsforbindelsen, ikke som personen som bruker dashboardet.

## Krav og installasjon

Du trenger **Home Assistant 2026.2.3 eller nyere**, Python 3.13.2 eller nyere i
HA-miljøet og en Samvev-server med **HA bridge, skjemaversjon 1**. Samvev må
oppdateres med [API-endringen i PR #28](https://github.com/pabben/samvev/pull/28)
før tilkoblingen kan brukes. Det eldre `/api/v1/integrations/items`-API-et alene
strekker ikke til.

Se [installasjonsveiledningen på norsk](docs/installation.md). Den beskriver
rekkefølgen, tilgangsnøkkel, deling, oppsett og fjerning. Den tekniske
[API-kontrakten](https://github.com/pabben/samvev/blob/feat/native-ha-bridge/docs/implementation/HA_BRIDGE_API.md)
er på engelsk. Oppsettet validerer faktisk nøkkel og API-versjon; en offentlig
helsesjekk regnes ikke som autorisasjon.

### HACS som egendefinert repo

Når implementasjonen er slått sammen til repoets standardgren:

1. Åpne menyen for egendefinerte repoer i HACS (**Custom repositories** på engelsk).
2. Legg til `https://github.com/pabben/samvev-homeassistant`, kategori **Integration**.
3. Last ned **Samvev** og start HA på nytt.
4. Åpne **Innstillinger → Enheter og tjenester → Legg til integrasjon → Samvev**.
5. Oppgi Samvev-adressen og en egen tilgangsnøkkel for forbindelsen.

Integrasjonen er ikke oppgitt som godkjent i HACS sitt standardutvalg.
Før PR-en er slått sammen, brukes manuell installasjon nedenfor.

### Manuell installasjon fra arbeidsgrenen eller ZIP

Last ned [arbeidsgrenen som ZIP](https://github.com/pabben/samvev-homeassistant/archive/refs/heads/feat/native-ha-entities.zip)
eller integrasjonspakken fra en vellykket [GitHub Actions-kjøring](https://github.com/pabben/samvev-homeassistant/actions/workflows/validate.yaml). Kopier bare `custom_components/samvev` til
`<HA-konfigurasjon>/custom_components/samvev`, og start HA på nytt.
Filen må ende på `<HA-konfigurasjon>/custom_components/samvev/manifest.json`,
uten en ekstra repo-mappe i stien. Legg deretter til integrasjonen gjennom GUI-et.
Utviklingsskriptene og Samvevs serverkode skal ikke kopieres til HA.

### Kan en agent gjøre installasjonen?

Ja, med administrasjonstilgang til den aktuelle installasjonen, for eksempel SSH
og tilgang til HA-konfigurasjonsmappen eller et egnet HACS-grensesnitt.
En MCP-forbindelse må tilby egne installasjonsverktøy for å kunne gjøre dette.
Vanlige verktøy for tilstandslesing, lysstyring og gjøremål er ikke tilstrekkelig.
Oppgradering av Samvev og eventuell HA-omstart må være uttrykkelig avtalt.

## Opprett nøkkel og velg deling

Bruk en egen, tilbakekallbar tilgangsnøkkel. Ikke legg en administratorøkt,
nettlesercookie, HA-nøkkel eller skjermcookie inn i integrasjonens oppsett.

[Oppsettskommandoen](scripts/provision_connection.py) bruker en midlertidig
Samvev-administratorøkt til å velge deling og opprette forbindelsens nøkkel.
Deretter logger den ut administratorøkten. HA får bare den nye nøkkelen.
Eksempel fra en maskin du stoler på, med Python 3.13:

```bash
python scripts/provision_connection.py \
  --url https://samvev.example.invalid --email manager@example.invalid \
  --name 'Samvev HA' --share-groceries --write-groceries \
  --share-household --messages --write-messages --calendar --write-calendar \
  --output "$HOME/samvev-ha-tilkobling.json"
```

Erstatt eksempeladressen og e-postadressen. Passordet oppgis uten at det vises.
Filen opprettes med filmodus `0600` og inneholder `base_url` og `api_token` til
HA-oppsettet. Nøkkelen skrives ikke til terminalen eller inn i repoet.

Utelat de aktuelle `--write-*`-flaggene for skrivebeskyttet tilgang. Bruk
`--inspect` for å finne tilgjengelige husstander, personer og kalenderkilder uten
å opprette en nøkkel. Velg `--household UUID` ved behov, gjenta `--person UUID`
for personers lesertilgang og `--calendar-source UUID` for hver importert kalender.
Hvem innholdet gjelder og hvem som kan lese det, er separate valg.
Se [deling og tilbakekalling](docs/installation.md#endre-deling-eller-trekk-tilbake-tilgang).

## Dashboard

[Dashboardveiledningen på norsk](docs/dashboard.md) forklarer hvordan du bruker
[examples/dashboard.yaml](examples/dashboard.yaml) som rå konfigurasjon for et
nytt HA-dashboard. Det bruker innebygde gjøremåls-, Markdown- og statuskort og
viser en komplett plan for i dag og i morgen fra kalenderentiteten.

Tilpass entitets-ID-ene til dem HA faktisk har opprettet. Eksemplet forutsetter
at forbindelsen heter **Samvev HA**.

For en annen kalenderpresentasjon kan dagsplankortet byttes med
[Calendar Card Pro](examples/calendar-card-pro.yaml) eller
[Week Planner Card](examples/week-planner.yaml). Installer valgt kort separat
via HACS. Begge er valgfrie; standardentitetene kan brukes av andre kort og
vanlige HA-automasjoner.

## Handlinger

Vanlige HA-handlinger som `todo.add_item`, `todo.update_item`, `todo.remove_item`,
`calendar.get_events` og `calendar.create_event` bruker standardentitetene.
Kalendergrensesnittet støtter også endring og sletting av egne avtaler.
Importerte kalendere annonserer ingen skrivefunksjoner. Oppretting av egne
repeterende avtaler støttes ikke; allerede importerte forekomster hentes fra Samvev.

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

`samvev.update_message` og `samvev.withdraw_message` tar `message_id` og eventuelt
`expected_revision` og `request_key`. Endring kan gjelde tekst, målgruppe,
viktighet, publisering og utløp. Uten angitt revisjon brukes sist observerte
revisjon. Samtidige endringer gir en synlig konflikt og ny henting, ikke stille
overskriving. HA kan bare endre beskjeder som denne forbindelsen selv har opprettet.

Velg `config_entry_id` når flere forbindelser er lastet. Bruk samme ikke-hemmelige
forespørselsnøkkel for nye forsøk på én handling, og en ny nøkkel for en ny handling.
Ingen av handlingene registrerer visning, lesing, bekreftelse eller oppgavefullføring.
De tekniske [API-detaljene og begrensningene](docs/api-contract.md) er på engelsk.

## Testing og utvikling

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/samvev
```

Testene bruker det faktiske HA-testmiljøet. Den engelske
[utviklingsveiledningen](docs/development.md) beskriver også rundturer mot faktisk
Samvev-kode og en isolert database med syntetiske data. Tester mot en simulert
HTTP-server alene regnes ikke som bevis på samvirke mellom implementasjonene.
Se [testbevis og skjermbilder](docs/validation.md) for utførte kontroller og
konkrete begrensninger. Testrapporten er på engelsk.

Utviklingstestene installerer ingenting i en aktiv husstands HA eller Samvev.
Fysisk Shelly Wall Display XL er ikke testet; nettleserkontroll ved tilsvarende
skjermstørrelse bekrefter ikke fastvarens oppførsel eller vedvarende innlogging.

MIT-lisens; se [LICENSE](LICENSE). Serverendringene ligger i det separate
Samvev-repoet og følger dets AGPL-lisens.
