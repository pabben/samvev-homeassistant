# Installasjon og tilkobling

Installasjonen består av tre deler: oppdatere Samvev med det nødvendige API-et,
installere integrasjonen i Home Assistant og opprette en egen tilgangsnøkkel med
valgt deling. Deretter kan du legge til [dashboardet](dashboard.md).

## Før du starter

Du trenger Home Assistant **2026.2.3 eller nyere** og en Samvev-installasjon med
**HA bridge, skjemaversjon 1**. Integrasjonen har versjon **0.2.0**. Den er testet
på HA 2026.2.3; dette er ikke en bekreftelse på testing av alle nyere HA-versjoner.
HA-miljøet må ha Python 3.13.2 eller nyere. Du trenger ikke installere Python
separat i en vanlig HA OS-installasjon.

Samvev-endringen må installeres først. Grunnstøtten er flettet gjennom
[Samvev-PR #28](https://github.com/pabben/samvev/pull/28) til
`feat/m3-family-hub` og legger til `047_home_assistant_bridge.sql`.
Utvidet skriving til eksisterende Samvev-innhold krever også migrasjon **048**
fra [Samvev-PR #31](https://github.com/pabben/samvev/pull/31) og uttrykkelig
deling som beskrevet nedenfor.

Følg Samvevs vanlige rutine for sikkerhetskopi og databasemigrasjon når en
oppgradering er avtalt. Denne veiledningen installerer eller oppgraderer ikke en
aktiv instans automatisk. [API-kontrakten](https://github.com/pabben/samvev/blob/feat/m3-family-hub/docs/implementation/HA_BRIDGE_API.md)
beskriver serverkravene. PR #25, som bygger inn Samvevs nettside i HA, er en
uavhengig løsning og er ikke nødvendig her.

## Kan installasjonen gjøres av en agent eller via MCP?

Ja, en agent kan utføre installasjonen hvis den har nødvendig
administrasjonstilgang, for eksempel SSH og filtilgang til HA-konfigurasjonen,
eller et administrasjonsgrensesnitt som støtter HACS og integrasjonsoppsett.
Oppgradering av Samvev og eventuell omstart av HA må være uttrykkelig avtalt.

En MCP-forbindelse må ha egne administrasjonsverktøy for å kunne gjøre dette.
Verktøy som bare leser entiteter, styrer lys eller behandler gjøremål, gir ikke
installasjonsadgang. MCP-navnet alene sier derfor ikke om en forbindelse kan
installere integrasjoner. Ingen offentlig eksponering av HA er nødvendig.

## Forbered bare Samvev og tilkoblingsfilen

En oppgave som gjelder serveroppgradering og oppretting av tilgangsnøkkel,
installerer ikke noe i Home Assistant. Den kan avsluttes med en kontrollert
Samvev-forbindelse og stien til den private filen. HACS-installasjon, kopiering
til HA, HA-omstart, GUI-oppsett, dashboard og fysisk Shelly-test er egne steg som
venter til de er avtalt. CLI-et nedenfor utfører ingen av disse HA-stegene og
endrer ikke miljøfiler, nettverksvern, proxy, vault eller leverandørtilkoblinger.

## 1. Installer integrasjonen i HA

### Via HACS

[HA-PR #1](https://github.com/pabben/samvev-homeassistant/pull/1) er flettet til
`main`. Installer integrasjonen som egendefinert repo:

1. Åpne menyen for egendefinerte repoer i HACS. På engelsk heter den **Custom repositories**.
2. Legg til `https://github.com/pabben/samvev-homeassistant` med kategorien **Integration**.
3. Last ned **Samvev**.
4. Start HA på nytt.
5. Fortsett med tilgangsnøkkel og GUI-oppsett nedenfor.

Dette er installasjon som egendefinert HACS-repo. Integrasjonen er ikke oppgitt
som godkjent i HACS sitt standardutvalg.

### Manuelt fra main eller ZIP-pakken

Du kan laste ned [main som ZIP](https://github.com/pabben/samvev-homeassistant/archive/refs/heads/main.zip),
eller integrasjonspakken fra en vellykket [GitHub Actions-kjøring](https://github.com/pabben/samvev-homeassistant/actions/workflows/validate.yaml):

1. Pakk ut arkivet.
2. Kopier bare `custom_components/samvev` til `<HA-konfigurasjon>/custom_components/samvev`.
3. Kontroller at filen ligger på `<HA-konfigurasjon>/custom_components/samvev/manifest.json`.
4. Start HA på nytt.

Hvis mappen finnes fra før, ta en kopi før den erstattes. Ikke legg hele repoet
som en ekstra undermappe. Utviklingsskriptene og Samvevs serverkode skal ikke
kopieres inn i HA.

## 2. Opprett en egen tilgangsnøkkel

Kjør [scripts/provision_connection.py](../scripts/provision_connection.py) på en
maskin du stoler på. Skriptet bruker Pythons standardbibliotek og trenger ikke
HA-utviklingsmiljøet. Eksemplene forutsetter Python 3.13 på Unix/Linux.
En lokal fillås hindrer samtidige kjøringer mot samme nøkkelfil.

Du oppgir en Samvev-administrators passord i en skjult ledetekst. Skriptet bruker
en midlertidig administratorøkt til å opprette forbindelsen og logger deretter
ut. HA får bare den nye, separat tilbakekallbare tilgangsnøkkelen.

### Finn tilgjengelige husstander, personer og kalenderkilder

Denne kommandoen viser ID-ene du kan velge, uten å opprette en forbindelse:

```bash
python scripts/provision_connection.py \
  --url https://samvev.example.invalid --email manager@example.invalid --inspect
```

Bytt ut eksempeladressen og e-postadressen med dine egne. Utskriften viser ID og
navn som trengs for valget, ikke fødselsdatoer, kontoenes e-postadresser,
rettigheter eller privat innhold. Samvev har for øyeblikket én felles handleliste,
med den stabile ID-en `groceries`.

### Velg hva forbindelsen skal kunne lese og endre

```bash
python scripts/provision_connection.py \
  --url https://samvev.example.invalid --email manager@example.invalid \
  --name 'Samvev HA' --household HOUSEHOLD_UUID \
  --share-groceries --write-groceries \
  --messages --write-messages --calendar --write-calendar \
  --share-household --calendar-source SOURCE_UUID \
  --output "$HOME/samvev-ha-tilkobling.json"
```

Erstatt `HOUSEHOLD_UUID` og `SOURCE_UUID` med valgte ID-er. Flagg og API-felter
beholder sine engelske programnavn.

- Utelat `--calendar-source SOURCE_UUID` hvis du bare vil bruke egne Samvev-avtaler. Gjenta flagget for hver importert kalender du vil dele.
- Utelat de aktuelle `--write-*`-flaggene for skrivebeskyttet tilgang.
- Bruk `--person PERSON_UUID`, eventuelt flere ganger, for innhold som de valgte personene har lesetilgang til. Hvem en avtale gjelder, er et separat spørsmål.
- Utelat `--share-household` hvis husstandsrettet innhold ikke skal deles.
- Bruk `--household UUID` for å velge husstand hvis administratoren administrerer flere.

Importerte kalendere beholder sine eksisterende leserrettigheter og er
skrivebeskyttet i HA. Skrivehandlinger som returnerer innhold, krever både lese-
og skriverettighet for den aktuelle innholdstypen.

### Gjenbruk én forbindelse og del alle nåværende personer og kilder

Følgende kommando velger alle seks `ha.*`-rettigheter, den eksisterende
handlelisten, husstandsrettet innhold og alle personer og kalenderkilder som
finnes i den valgte husstanden ved kjøringen:

```bash
python scripts/provision_connection.py \
  --url https://samvev.example.invalid --email manager@example.invalid \
  --name 'Samvev HA' --household HOUSEHOLD_UUID \
  --share-groceries --write-groceries \
  --messages --write-messages --calendar --write-calendar \
  --share-household --all-current-persons --all-current-calendar-sources \
  --allow-shared-native-writes --reuse-existing \
  --output "$HOME/samvev-ha-tilkobling.json"
```

`--allow-shared-native-writes` krever serverendringen med migrasjon **048** og
policyfeltet `allowSharedNativeWrites`. Feltet er som standard `false`; flagget
gir uttrykkelig tillatelse til å endre og trekke tilbake **eksisterende beskjeder
opprettet i Samvevs webgrensesnitt**, når hele målgruppen er tillatt. Det tillater
også endring og avlysning av ekte, native Samvev-avtaler opprettet av en annen
aktiv HA-forbindelse i samme husstand. Serveren kontrollerer målgruppe og revisjon
for hver handling. Det gir ikke skriverettighet hos Google,
Outlook eller Spond. Originalforfatteren beholdes, og HA-forbindelsen registreres
som aktør for endringen. Flagget skal bare brukes når slik skriving er avtalt;
utelat det for den tidligere begrensningen til forbindelsens eget innhold.
Arbeids-/systemgenererte beskjeder og generelle eksterne produsenters avtaler
forblir skrivebeskyttet. Eksisterende skjermmottakere kan beholdes ved uttrykkelig
husstandsfullmakt, men HA kan ikke legge til eller erstatte skjermmottakere.

Det undersøkte Samvev-webgrensesnittet har **ingen lokal kalendereditor eller
medlems-API for å opprette, endre og slette egne avtaler**. Det viser avtaler og
administrerer kalenderimporter. Denne leveransen legger ikke til en slik editor;
kalenderens skrivefunksjoner gjelder de eksisterende native HA-avtalene. En
rundtur fra UI-opprettet lokal avtale er derfor ikke påstått. HAs eget
kalendergrensesnitt kan fortsatt opprette og endre støttede native avtaler.

Personene velges som **lesere**, uavhengig av hvem avtaler gjelder. Alle valgte
ID-er kontrolleres mot samme husstand. Kalenderutvalget omfatter nåværende
kilde-ID-er som Samvev returnerer, også deaktiverte kilder i eksisterende
forbindelser. CLI-et aktiverer eller gjenkobler ikke kilder og endrer ikke deres
leserrettigheter. Bare gyldig, tillatt kildeinnhold blir tilgjengelig i HA.

Dette er et **statisk øyeblikksvalg**. Personer og kilder som opprettes senere,
blir ikke automatisk delt. For å ta dem med må administratoren uttrykkelig kjøre
kommandoen igjen med de aktuelle `--all-current-*`-flaggene. Alle delingsvalg i
kommandoen erstatter hele forbindelsens eksportregel; behold derfor de ønskede
flaggene ved senere kjøringer. Utelatte valg kan fjerne tidligere deling.

Når `--output` ikke finnes, oppretter skriptet én ny forbindelse og en ny fil med
filmodus `0600`, altså bare tilgjengelig for filens eier. Normal utskrift er
**bare filstien**. Nøkkel, administratorpassord, personnavn, kilde-ID-er og
innhold skrives ikke ut. `--inspect` er det separate, uttrykkelige
administrasjonsvalget som viser ID-er og navn.

Med `--reuse-existing` og en eksisterende fil kontrolleres filtype, eier, modus
`0600`, baseadresse, husstand, forbindelsesidentitet, nøkkel og nøyaktige
rettigheter før deling kan endres. Filen må være en vanlig fil uten symbolsk
lenke eller ekstra hardlenker. Nøkkelen kontrolleres som separat bearer-identitet,
uten administratorcookies. Ved uendret deling opprettes verken ny forbindelse,
ny nøkkel eller ny delingsrevisjon. Nøkkelfilen overskrives ikke. Endret deling
sendes én gang med observert `expectedRevision`; en konflikt krever ny vurdering,
ikke blind overskriving. En tom, privat `.lock`-fil ved siden av nøkkelfilen
brukes for å hindre lokale parallelle kjøringer. Låsen slippes når prosessen
avsluttes; låsfilen kan bli liggende.

Uten `--reuse-existing` stanser en eksisterende fil kjøringen før innlogging.
En avvist nøkkel, annen husstand eller manglende rettigheter stanser gjenbruk;
skriptet roterer ikke nøkler automatisk. Hvis filen mangler og en aktiv
forbindelse allerede har samme navn, opprettes ingen dublett. Gjenfinn den
private nøkkelfilen eller avklar den eksisterende forbindelsen i Samvev.

Ved feil etter nyoppretting forsøker skriptet å tilbakekalle **bare den nye
forbindelsen**. En gjenbrukt forbindelse tilbakekalles aldri som feilopprydding.
Ved tapt svar under selve opprettingen gjentas ikke POST automatisk: serveren
kan allerede ha opprettet forbindelsen. Kontroller metadata i Samvev før videre
forsøk. Opprettings-API-et gir ingen garanti om nøyaktig én oppretting over et
uavklart nettverksavbrudd eller mellom forskjellige nøkkelfiler/maskiner.
Skriptet følger ikke HTTP-omdirigeringer og lagrer ikke administratorøkten.

## 3. Koble til i HA

1. Åpne **Innstillinger → Enheter og tjenester → Legg til integrasjon**.
2. Søk etter **Samvev**.
3. Oppgi Samvev-adressen fra `base_url` og tilgangsnøkkelen fra `api_token` i filen du nettopp opprettet.
4. Fullfør oppsettet og kontroller at tilkoblingsstatusen blir **Tilkoblet**.
5. Legg til [dashboardeksemplet](dashboard.md).

Adressen må være tilgjengelig **fra HA**. HTTPS bruker vanlig
sertifikatkontroll. HTTP er beregnet på et betrodd lokalnett eller et isolert
testmiljø. Forbindelsen kontrollerer nøkkel, installasjonsidentitet og API-versjon;
en offentlig helsesjekk alene er ikke nok. Samvev trenger ingen tilbakekobling
til HA.

Ikke bruk en administratorøkt, nettlesercookie, HA-nøkkel eller skjermcookie som
tilgangsnøkkel til denne integrasjonen.

## Endre deling eller trekk tilbake tilgang

Samvev bestemmer delingen. HA kan ikke utvide sine egne rettigheter.
Administratoren kan inspisere og erstatte delingsreglene eller trekke tilbake
en enkelt nøkkel eller hele forbindelsen.

For administrasjon gjennom API-et brukes de vanlige administratorøktene med
CSRF-beskyttelse, ikke HA-forbindelsens nøkkel:

| Endepunkt | Formål |
|---|---|
| `GET /api/v1/households/:householdId/integrations` | Vis forbindelser og nøkkelmetadata |
| `GET/PATCH …/integrations/:connectionId/ha-sharing` | Les eller erstatt hele delingsregelen med `expectedRevision` |
| `POST …/integrations/:connectionId/credentials` | Opprett en erstatningsnøkkel med valgte rettigheter og forbindelsens `expectedRevision` |
| `POST …/integrations/:connectionId/credentials/:credentialId/revoke` | Trekk tilbake den gamle nøkkelen med nøkkelens `expectedRevision` |
| `POST …/integrations/:connectionId/revoke` | Trekk tilbake hele forbindelsen med forbindelsens `expectedRevision` |

Se [delings- og nøkkelkontrakten](https://github.com/pabben/samvev/blob/feat/native-ha-bridge/docs/implementation/HA_BRIDGE_API.md)
og [administrasjon av integrasjonsnøkler](https://github.com/pabben/samvev/blob/feat/native-ha-bridge/docs/implementation/M3_API.md)
for de tekniske detaljene. Disse API-beskrivelsene er på engelsk.

Hvis `groceries` fjernes fra `listIds`, stoppes lesing og endring av handlelisten.
En tom husstands-/personmålgruppe stopper deling av beskjeder og kalender.
Importerte kilder krever både valgt kilde og fortsatt lesetilgang.

Tilbakekalling gjelder straks på serveren. HA fjerner tidligere viste data ved
neste forespørsel, normalt innen den planlagte hentingen hvert 30. sekund.
Avvist nøkkel starter HAs flyt for ny autentisering.

## Endre adresse, bytt nøkkel eller fjern integrasjonen

Bruk menyvalget for å endre integrasjonens oppsett, **Reconfigure** på engelsk,
for å bytte serveradresse eller nøkkel. Oppsettet må fortsatt vise til samme
Samvev-installasjon og forbindelse. En annen forbindelse legges til som en ny
integrasjon. Ny autentisering godtar en erstatningsnøkkel for samme forbindelse.

Vanlig gjeninnlasting stopper gamle lyttere, tidtakere og bakgrunnsoppgaver og
laster entitetene på nytt. Når integrasjonen fjernes fra HA, ryddes entitetene
og det lokale lageret for forespørselsnøkler.

Fjerning i HA tilbakekaller **ikke** nøkkelen i Samvev og sletter ikke
handlevarer, beskjeder eller avtaler. Trekk tilbake forbindelsen i Samvev hvis
tilgangen også skal opphøre der. Ved manuell avinstallasjon fjernes den kopierte
komponentmappen etter at integrasjonen er fjernet fra HA.

HA-brukere med tilgang til disse entitetene kan se innholdet som er delt med
forbindelsen. Dashboardtilgang i HA er ikke en egen personrettighet i Samvev.
Bruk separate forbindelser med smal deling og passende HA-tilgang hvis
målgruppene er forskjellige.

## Tilbakeføring

Migrasjon 047 utvider eksisterende rettigheter, legger til uttrykkelig deling og
varige forespørselskvitteringer og støtter forbindelsen som egen aktør. Tidligere
nøklers betydning og kontrollsummene for eldre migrasjoner beholdes. Kalenderen
bruker Samvevs eksisterende datamodell.

For å trekke tilbake HA-integrasjonen kan du avslutte forbindelsen og deaktivere
eller fjerne integrasjonen. Behold den utvidede databasestrukturen og innholdet.
Ikke kjør en destruktiv nedmigrasjon eller gjenopprett en gammel database over
nyere endringer.

En eldre serverversjon er ikke automatisk kompatibel med beskjeder fra
integrasjonsaktører eller egne heldagshendelser. Tilbakeføring til et eldre
serverimage er ikke testet her. Foretrekk feilretting på den nye versjonen, eller
lag og test en egen kompatibilitets- og dataplan. Full tilbakeføring av databasen
krever en separat kontrollert sikkerhetskopi og Samvevs vanlige gjenopprettingsrutine.
