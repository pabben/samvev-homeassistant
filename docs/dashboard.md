# Dashboard og Shelly Wall Display XL

Integrasjonen gir vanlige HA-entiteter. Dashboardet bygges i HA og krever verken
innbygging av Samvevs nettside eller endringene i PR #25.

## Legg til dashboardet

1. Legg til integrasjonen med forbindelsesnavnet **Samvev HA**.
2. Finn de faktiske entitetene under **Innstillinger → Enheter og tjenester → Samvev**.
3. Opprett et dashboard og åpne den rå konfigurasjonen. Ta kontroll over dashboardet først hvis HA ber om det.
4. Lim inn [examples/dashboard.yaml](../examples/dashboard.yaml).
5. Bytt entitets-ID-er hvis du brukte et annet navn eller HA har lagt til et suffiks.
6. Legg til hver importerte kalender du har delt, som et eget kalender-/dagsplankort, eller samle dem i et av de valgfrie kortene nedenfor.

| Eksempel på entitet | Formål |
|---|---|
| `todo.samvev_ha_groceries` | Felles handleliste med avkryssing, tillegg, endring og sletting |
| `sensor.samvev_ha_messages` | Antall aktive beskjeder, med alle beskjedene i attributtet `messages` |
| `calendar.samvev_ha_samvev` | Egne Samvev-avtaler og vanlig kalenderhenting for valgte tidsrom |
| `sensor.samvev_ha_connection_status` | Tilkoblingsstatus, henteintervall og siste vellykkede henting |
| `sensor.samvev_ha_last_success` | Tidspunktet for siste vellykkede henting |

## Hva standarddashboardet viser

Eksemplet bruker HAs innebygde gjøremåls-, Markdown- og entitetskort.
Dagsplankortet leser kalenderentitetens `agenda`-attributt, med komplette grupper
for i dag og i morgen i husstandens tidssone. Dette dekker også søndag/mandag,
samtidige avtaler, avtaler som går over midnatt og heldagshendelser.

Vanlige kalenderkort og automasjoner kan fortsatt hente alle tillatte hendelser
innen et valgt tidsrom. Visningen for to dager begrenser ikke kalender-API-et.
Også tidligere avtaler fra dagens dato er med i dagsplanen.

Utilgjengelig eller utdatert innhold merkes tydelig. Hvis en importert kalenders
synkroniserte tidsrom ikke dekker begge dagene, blir den utilgjengelig fremfor å
late som dagsplanen er komplett og tom. Attributtene `source_freshness`,
`last_source_sync`, `source_error` og `last_complete_window` skiller feil hos
kalenderkilden fra feil på forbindelsen mellom HA og Samvev.

Kalenderleverandørens mellomlager og Samvevs importintervall kan gi forsinkelse
i tillegg til HAs henting hvert 30. sekund. Tekst i integrasjonens oppsett,
entiteter og handlinger finnes på norsk bokmål og engelsk (`nb`/`en`).
Dashboardeksemplet er på norsk og kan redigeres i HA.

Bruk samme tidssone på HA-visningen og i husstanden for riktig formatering av
klokkeslett. Serveren bevarer tidssoneangitte tidspunkt og heldagshendelsenes
datoer.

## Valgfrie kalenderkort

[Calendar Card Pro](https://github.com/alexpfau/calendar-card-pro) og
[Week Planner Card](https://github.com/FamousWolf/week-planner-card) kan brukes
som alternativer. Konfigurasjonen er kontrollert mot prosjektenes egne eksempler.
Installer valgt kort separat gjennom HACS og oppdater nettleseren/ressursene slik
kortets veiledning beskriver. Ingen av dem er påkrevd eller følger med Samvev.

Bytt ut dagsplankortet med
[calendar-card-pro.yaml](../examples/calendar-card-pro.yaml) eller
[week-planner.yaml](../examples/week-planner.yaml). Begge viser to dager.
Legg inn egne og uttrykkelig delte importkalendere i den aktuelle entitetslisten.

Calendar Card Pro bruker `entities` og `days_to_show`. Week Planner bruker
`calendars`, `days` og `startingDay`. Ikke bland innstillingene mellom kortene.
HAs innebygde kalenderkort og automasjoner fungerer uavhengig av disse tilleggene.

## Kontroll av skjermvisning

Seksjonene vises i tre kolonner ved 1280 piksler og stables på smale skjermer.
Beskjedtekst brytes over flere linjer. Flere aktive beskjeder beholder hver sin
avsender og viktighet; de legges ikke som en lang tekst i sensorens tilstand.
Det innebygde gjøremålskortet har sine vanlige berørings- og tastaturkontroller.
Se [testbevis og skjermbilder](validation.md) for utførte kontroller. Den tekniske
testrapporten er på engelsk.

Nettleservisning er kontrollert ved 1280×752 og 390×844 i lyst og mørkt tema.
Dette er ikke en fysisk test av Shelly. Faktisk Shelly-fastvare, berøring,
rulling, ytelse og vedvarende innlogging må fortsatt prøves på enheten.
Integrasjonen krever ikke offentlig eksponering av HA eller endringer i nettverksvern.
