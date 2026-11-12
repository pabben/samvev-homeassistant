# Samvev for Home Assistant

Eget utviklingsrepo for Home Assistant-siden av integrasjonen med [Samvev](https://github.com/pabben/samvev).

## Status

Repoet inneholder foreløpig prosjektgrunnlaget. En installerbar integrasjon er ikke levert eller testet ennå.

[Samvev PR #25](https://github.com/pabben/samvev/pull/25) gjelder støtte for å vise Samvevs `/display` i et Home Assistant-dashboard. Endringene i den PR-en blir i Samvev-repoet. Skjermløsningen må fortsatt verifiseres på aktuell maskinvare.

## Ansvarsdeling

| Repo | Ansvar |
|---|---|
| `pabben/samvev` | Samvevs API, tilgangsstyring, skjermparing, visningsdata og iframe-støtte |
| `pabben/samvev-homeassistant` | HA-oppsett, klient mot Samvev, entiteter, handlinger, datautveksling og eventuelle dashboardkort |

Integrasjonen skal kunne utvikles og versjoneres separat. Et eget repo innebærer ikke at det må driftes en ekstra server.

## Planlagt omfang

- Enkel tilkobling fra Home Assistant til Samvev.
- Utvalgte Samvev-data som HA-entiteter.
- Avgrensede handlinger som kan brukes i HA-automasjoner.
- Datautveksling for avtalte behov, for eksempel kalender, påminnelser og hjemmestatus.
- Egne tester, installasjonsveiledning og oversikt over kompatible Samvev-versjoner.

Detaljer, datatilgang og retning på dataflyten må avklares per funksjon. Listen beskriver ønsket utvikling, ikke tilgjengelig funksjonalitet.

## Første utviklingsoppgave

1. Undersøk hvilke API-er og autentiseringsmekanismer Samvev faktisk tilbyr.
2. Dokumenter nødvendige API-kontrakter og eventuelle mangler.
3. Lever en liten, fungerende HA-integrasjon med tilkoblingsoppsett og én skrivebeskyttet funksjon valgt ut fra tilgjengelig API og dokumenterte behov.
4. Verifiser tilkobling, tilgangsgrenser, utilgjengelig server og fjerning av integrasjonen.

Nødvendige endringer i Samvev følges opp som egne issues eller PR-er der. Ikke kopier Samvevs backend eller forretningslogikk inn hit.

## Utvikling

Se [AGENTS.md](AGENTS.md) for arbeidsregler. Bruk syntetiske testdata. Ikke legg inn tokens, passord eller husstandsdata i repoet.
