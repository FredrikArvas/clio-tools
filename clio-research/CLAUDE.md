# clio-research — CLAUDE.md

## Syfte
Autonomt, multi-lingualt forskningsverktyg för epistemologiskt öppna frågor.
Triggas av protokollfil i inbox/. Kör sekventiellt genom 8 faser.

## Prioriteringar
1. Fullständighet före hastighet — det är OK om en körning tar 12–24 timmar
2. Skicka statusmail vid varje fas-avslut (använd status_mailer.py)
3. Fråga via mail (input_needed) om söktermer är oklara — vänta inte på svar,
   fortsätt med nästa fas och återkoppla när svar kommit
4. Indexera alltid i Qdrant (vigil_research) — även om rapporten är tunn

## Felhantering
- Databas otillgänglig: logga, fortsätt, notera i rapporten
- Rate limit: exponential backoff, max 3 försök
- Parsing-fel på fulltext: hoppa över fulltext, använd abstract
- Noll resultat i en fas: skicka anomali-mail, fortsätt

## Återupptagning
State sparas efter varje fas i running/[run_id].json.
--resume läser state och fortsätter från senaste slutförda fas.

## Språk
Söksträngar genereras på källspråket för varje databas.
Summarering sker alltid på svenska i slutrapporten.
Citat från källor behålls på originalspråk med svensk översättning i parentes.
