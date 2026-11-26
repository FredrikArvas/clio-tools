# Plan: teknisk portering av Larry Hatch *U* Database till Odoo

**Projekt:** NCC `#afu` — AFU-analys (Archives for the Unexplained), nr 18
**Skapad:** 2026-09-26
**Status:** klar att köras i egen session
**Omfattning:** enbart Larry Hatch. Mappning in i `uap`-databasens encounter-lista ligger *utanför* denna plan.

Denna plan är självbärande — den förutsätter ingen kontext från sessionen där den skrevs.

---

## 1. Mål och beslutade premisser

Vi bygger en **ny Odoo-databas `afu_archives`** som innehåller **en modell per källarkiv** från AFU. Syftet är att *redovisa vad andra forskare gjort*, i deras egna scheman, läsbart för oss och för andra.

Beslutade premisser (diskuterade och fastställda — ifrågasätt dem inte i onödan):

1. **Egen Odoo-databas**, inte nya modeller i `uap`. Skälet är delbarhet: arkivet ska kunna lämnas vidare utan att exponera eller kräva resten av UAP-projektet.
2. **En databas, flera modeller.** Inte en databas per arkiv. Larry Hatch blir en modell; PrimeBase, USOcat, NavCAT m.fl. blir egna modeller i samma databas senare.
3. **Trogen 1:1-portering.** Källans fält bevaras som de är. Inga tolkningar, inga härledda klassificeringar vid importtillfället.
4. **Klassificering är ett separat, omkörbart steg.** Mappning till `uap.encounter` sker senare, från den porterade databasen, och ska kunna köras om när mappningsregler förbättras.
5. **Plain export som komplement.** När schemat finns ska en SQLite- eller CSV-export kunna genereras, så artefakten är användbar utan Odoo 19 + custom-modul.

### Designkonsekvens som följer av delbarheten

**Modulen får INTE bero på `clio_uap`.** `depends` ska vara `["base"]` och inget mer. Annars måste en mottagare installera hela UAP-applikationen för att läsa Larrys data. Detta är ett hårt krav, inte en preferens.

---

## 2. Varför vi porterar från `U.RND` och inte från PDF:en

Det finns en PDF, `Larry Hatch - full text.pdf`, som är programmets egen ASCII-export (`Option [E] EXPORT ASCII FILES`). Den innehåller datum, tid, duration, koordinater, precisionskod, kontinent/land/delstat, strangeness, credibility, summary, Ref# + sidnummer och terräng.

**Den saknar attributmatrisen: 8 rader × 8 booleska attribut = 64 flaggor per fall.**

Det är i attributen den analytiska substansen ligger — landning, entiteter, transmediumrörelse, myndighetsinblandning, fysiska spår. Utan dem går `encounter_class`, `intelligence_indicator`, observables och `official_response` inte att sätta på saklig grund. Attributen finns bara i `U.RND`.

PDF:en är däremot **ovärderlig som ground truth** för att verifiera binärparsningen. Se avsnitt 5.

> Notera: summary klipps *inte* i PDF:en. Manualen är explicit: `SUMMARY: A 78-character text field`. Fältet är 78 tecken i källan.

---

## 3. Miljö och filer

### Server

```
clioadmin@100.107.127.104
```

Odoo 19 kör i Docker:

| Sak | Värde |
|---|---|
| Container | `odoo19-odoo-1` |
| Port (host) | `8079` → 8069 i containern |
| Postgres | container `odoo19-db-1` (postgres:15) |
| Compose-fil | `/opt/odoo19/docker-compose.yml` |
| DB-växlare | `/opt/odoo19/switch-db.sh` |
| Befintlig UAP-databas | `uap` |

**Addons-katalog:** `~/clio-odoo-addons` på hosten är monterad som `/mnt/addons/arvas` i containern. Ett nytt modul läggs där — **ingen docker-compose-ändring och ingen omstart av containern behövs**, bara en modulinstallation.

Befintlig modul att följa konventioner från: `~/clio-odoo-addons/clio_uap` (models/, views/, security/ir.model.access.csv, tests/, `__manifest__.py` med version `19.0.x.y.z`, author "Fredrik Arvas / Arvas International AB", license LGPL-3).

### Odoo-credentials

Läses från `~/19.0/clio-tools/.env` (och `.env` i underprojektet med `override=True`):

```python
from pathlib import Path
from dotenv import load_dotenv
d = Path('/home/clioadmin/19.0/clio-tools')
load_dotenv(d / '.env')
load_dotenv(d / 'clio-afu' / '.env', override=True)

url  = os.environ["VIGIL_ODOO_URL"]       # http://100.107.127.104:8079
db   = os.environ["VIGIL_ODOO_DB"]        # uap  — ÄNDRA till afu_archives
user = os.environ["VIGIL_ODOO_USER"]      # clio-bot@arvas.international
pwd  = (os.environ.get("VIGIL_ODOO_PASSWORD")
        or os.environ.get("ODOO_ADMIN_PASSWORD")
        or os.environ.get("ODOO_PASSWORD"))
```

`VIGIL_ODOO_USER` är `clio-bot@arvas.international`, uid 5 i `uap`. **Fallgrop:** om `authenticate()` returnerar `False` och du ändå kör `execute_kw`, blir felet `Fault 3: Access Denied` — vilket ser ut som ett rättighetsproblem men är en misslyckad inloggning. Kontrollera alltid uid.

### Källfiler

Projektmapp: `~/19.0/clio-tools/clio-afu/`

```
data/downloads/Databases/Larry Hatch/
  original/
    U.RND                              2 029 786 byte  ← porteringskällan
    larry hatch database manual.doc      166 KB  (OLE/Word, 24-sidig manual)
    USOURCES.DOC                          56 KB  (ASCII: Ref# → fulla källhänvisningar)
    README.DOC                           9,2 KB  (ASCII)
    README.BAT                             17 B
    WM.VCE                                72 KB  (ljudfil, "Flying Saucer Theme")
  derivations/
    Larry Hatch - full text.pdf          2,6 MB  ← ground truth för verifiering
```

Lokal kopia finns även i `C:\Users\fredr\Dropbox\projekt\Clio-projekt\Clio Resarch\18_AFU-analys\Larry Hatch\`.

### Extrahera manualtexten

`.doc`-filen är OLE. Det finns ingen antiword/catdoc på servern. Grov men fullt användbar extraktion:

```python
import re
p = '/home/clioadmin/19.0/clio-tools/clio-afu/data/downloads/Databases/Larry Hatch/original/larry hatch database manual.doc'
t = open(p, 'rb').read().decode('latin-1')
t = re.sub(r'[^\x20-\x7e\n]+', ' ', t)
t = re.sub(r' {3,}', '  ', t)
open('/tmp/lh_manual.txt', 'w').write(t)
```

Sök sedan på rubrikerna (offset varierar, sök på strängen):

| Appendix | Innehåll |
|---|---|
| `APPENDIX I: SETTING SEARCH LIMITS` | sökfilter, 90+ sökvägar |
| `APPENDIX II:  ATTRIBUTES MATRIX` | de 64 attributen — **återgivna i sin helhet i avsnitt 7 nedan** |
| `APPENDIX III:  CONTINENT and COUNTRY MNEMONIC CODES` | kontinent- och landkoder — **måste extraheras** |
| `APPENDIX IV:  The STATE/PROVINCE Field` | delstat/provins — **måste extraheras** |

---

## 4. Fastställda fakta om `U.RND`-formatet

Detta är verifierat, inte antaget:

```
filstorlek                2 029 786 byte
(2 029 786 − 122) / 112 = 18 122.000     exakt, ingen rest
```

**Formatet är fixbreddsposter** — en DOS/BASIC random access-fil ("RND"):

| Del | Storlek |
|---|---|
| Filhuvud | 122 byte (innehåller ASCII-strängen `Rec. #18120 EDITED.`) |
| Poster | 18 122 × 112 byte |

**Postlayout, delvis känd:**

| Offset i posten | Storlek | Innehåll |
|---|---|---|
| 0–30 | 31 byte | binära fält — **ska kartläggas, se fas 1** |
| 31–108 | 78 byte | `SUMMARY`, ASCII |
| 109–111 | 3 byte | okänt — ska kartläggas |

Verifiering av summary-offset: av alla ASCII-sekvenser ≥ 25 tecken i filen ligger 16 178 st på `offset mod 112 == 31`, och det vanligaste avståndet mellan två sekvensstarter är 112 (16 178 förekomster). Första posterna:

```
offset  143  CHALDEA:EZEKIEL:FIERY SPHERE LANDS/4 SUPPORTS:TAKEN FOR A RIDE:see Bible acct.
offset  255  TYRE =SUR,LEBANON:SIEGE/ALEXANDER the GREAT:FLYING SHIELD BEAMS^:WALLS CRUMBLE
offset  367  HADRIA,ROMAN EMP:'ALTAR' IN SKY:MAN IN WHITE:12 SUCH BETWEEN 222 AND 90 B.C.
```

I de 31 byten ligger bl.a. 3-tecken koder som nullterminerade strängar (`CHL`, `TYR`, `FI.`) — synliga i hexdump kring offset 0x80–0x92.

De 31 + 3 = 34 byten ska rymma: år, månad, dag, timme, minut, fyra precisionssiffror, duration (0–32000), longitud och latitud i grader/minuter/sekunder, elevation, relativ altitud, kontinent, land, delstat (3 tecken), strangeness (0–F), credibility (0–F), Ref# , sidnummer (0–999), terräng, och **64 attributbitar (8 byte)**. Det blir tight — räkna med bitpackning, inte ett byte per fält.

---

## 5. Verifieringsstrategin — det här är planens viktigaste del

PDF:en och `U.RND` innehåller **samma poster i samma ordning**. Manualen: *"*U* records are in strict chronological order."* Post 1 i båda är CHALDEA/EZEKIEL år −593. Antalet stämmer: 18 122 i båda.

Det ger en exakt korrespondens `binärpost[i] ↔ PDF-post[i]`, och därmed **18 122 kända värden per fält** att lösa byteoffsetarna mot.

### Metod: brute-force-lösare

Bygg en lösare i stället för att gissa layouten:

1. Parsa PDF:en till 18 122 poster med kända fält (se avsnitt 6 för regexen).
2. För varje målfält (t.ex. `year`), loopa över alla kandidater: byteoffset 0–33, bredd 1/2/4, endianness little/big, signed/unsigned, samt BCD och "packad" tolkning.
3. Räkna andelen av de 18 122 posterna där kandidaten ger exakt PDF-värdet.
4. **Acceptera först vid 100 % match.** Vid 99,x % — undersök avvikelserna, de indikerar antingen fel tolkning eller kända datafel.

Fält som går att lösa direkt så här: år, månad, dag, timme, minut, duration, longitud (grad/min/sek), latitud, de fyra precisionssiffrorna, strangeness, credibility, Ref#, sidnummer.

Fält som kräver mappning mot kodlistor (Appendix III/IV) men samma metod: kontinent, land, delstat, terräng.

### Attributbitarna — svårast, men verifierbara

De 64 attributen finns inte i PDF:en, så de kan inte lösas mot ground truth direkt. Använd i stället **semantisk korrelation mot summary-texten**, som är en stark signal:

| Attribut | Förväntad korrelation i summary |
|---|---|
| `SUB` | "SUBMERGE", "RISES FROM", "INTO LAKE/SEA" |
| `LND` | "LANDS", "LANDING", "SETS DOWN" |
| `SCR` | "SCR" (Larrys egen förkortning för saucer) |
| `NLT` | "NLT", "NIGHT LIGHT" |
| `OID` | "OID", "HUMANOID" |
| `RBT` | "RBT", "ROBOT" |
| `PHT` | "PHOTO", "FILM", "VIDEO" |
| `EME` | "EME", "CAR STALLS", "ENGINE" |
| `ABD` | "ABDUCT", "TAKEN" |
| `BBK` | "BLUEBOOK", "BBK" |

Metodik: hitta de 8 byten som ger högst semantisk korrelation över alla 64 bitar samtidigt. När kandidatoffseten är rätt ska *flera* bitar samtidigt korrelera starkt med sina respektive nyckelord — fel offset ger brus över hela linjen. Bitordningen inom byten (rad/kolumn, MSB/LSB) faller ut av vilka nyckelord som matchar vilken bit.

Exempelpost att kontrollera manuellt: post 1, `CHALDEA:EZEKIEL:FIERY SPHERE LANDS/4 SUPPORTS:TAKEN FOR A RIDE` — ska ha `LND` (lands), `ABD` (taken for a ride), `SCR` (sphere), `HST` (historical), rimligen `OID`/`FIG`.

**Acceptanskriterium för fas 1:** en fältspecifikation där varje fält har en dokumenterad matchgrad mot ground truth, och där de fält som inte nått 100 % är uttryckligen listade som osäkra.

---

## 6. PDF-parsern (för ground truth) — och en bugg att inte återinföra

Det finns ett befintligt script, `~/19.0/clio-tools/clio-afu/afu_import.py`, som parsar PDF:en. **Använd det inte som det är.** Dess regex tappar 8 103 av 18 122 fall. En backup av originalet ligger som `afu_import.py.bak-20260926`.

Radformatet i PDF:en:

```
    1: -593/01/01 00:10    60   46:10:00 E  31:00:00 N 3111 MDE IRQ CHL 8:4
CHALDEA:EZEKIEL:FIERY SPHERE LANDS/4 SUPPORTS:TAKEN FOR A RIDE:see Bible acct.
Ref#  2 VALLEE:UFOS IN SPACE:Anatomy/phenon.         Page No. 2 : PASTURE
```

Fälten: `löpnr: år/månad/dag tid duration lon E|W|Z lat N|S|Q precisionskod kontinent land delstat strangeness:credibility`, därefter summary på rad 2 och `Ref# nr källa … Page No. n : terräng` på rad 3.

**Korrigerad regex** (verifierad: matchar 18 122/18 122, noll dedupliceringskollisioner):

```python
DATA_LINE_RE = re.compile(
    r"^\s*(\d+):\s+(-?\d{1,4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}:\d{2})"
    r"\s+(\d+)"
    r"\s+(\d+):(\d+):(\d+)\s+([EWZ])"
    r"\s+(\d+):(\d+):(\d+)\s+([NSQ])"
    r"\s+(\S{4})\s+([A-Z0-9.\-]{3})\s+([A-Z0-9.\-]{3})"
)
```

Fyra fel i originalregexen, alla bekräftade:

| Fel | Effekt |
|---|---|
| `^\s+` i stället för `^\s*` | Case-numret är högerjusterat i ett 5 tecken brett fält. Poster med nr ≥ 10000 saknar inledande blanksteg helt → **8 103 poster tappades** |
| `(E\|W)` | Longitudriktning kan vara `Z` (nollmeridian/okänd) — 71 poster |
| `(N\|S)` | Latitudriktning kan vara `Q` — 4 poster |
| `[A-Z]{3}` för region/land | Koder kan innehålla punkt eller bindestreck: `FI.`, `RM.`, `---` |

Textextraktion ur PDF:en görs med `pymupdf` (finns installerat): `fitz.open(path)`, `"\n".join(p.get_text() for p in doc)` → 4 332 653 tecken.

### Datumfallgropar

- **`3111` är INTE en typkod.** Manualen: *"ACCURACY: För YEAR, MONTH, DAY och TIME: 0 = DOES NOT APPLY, 1 = UNKNOWN, 2 = APRX, 3 = KNOWN."* Fyra siffror, en per fält. Det gamla scriptet läste första siffran som en UFO-typkod och härledde `encounter_class` ur den — eftersom årsprecisionen nästan alltid är `3` blev i praktiken hela databasen klassad likadant. **Bevara precisionskoden som fyra separata heltalsfält. Härled ingenting ur den.**
- **Dag `00` betyder okänd dag** — 1 118 poster. Månad `00` förekommer också. Bevara nollan som den är; precisionskoden dokumenterar redan osäkerheten. Konvertera inte till `01` i porteringslagret.
- **8 poster har år < 1000**, inklusive negativa (−593, −322, −213, −170). Odoo `Datetime` kan inte lagra dem. I porteringsmodellen: lagra år/månad/dag/timme/minut som **separata heltalsfält**, och lägg ett *beräknat* `Datetime`-fält vid sidan som är `False` när datumet inte är representerbart. Då tappas ingen post.
- Minuter anges i 10-minutersintervall (manualen: `MINUTES: (00-50)`).
- Sekunder i koordinater är avrundade till närmaste 20 sekunder (≈ 630 m). Notera precisionen, avrunda inte vidare.

---

## 7. Attributmatrisen — Appendix II i sin helhet

64 attribut, 8 rader × 8 kolumner, alla booleska. Detta är seeddatan till taxonomin. Koderna är Larrys egna och ska bevaras som `code`.

**Rad 1 — observatörens plats**

| Kod | Betydelse |
|---|---|
| `MAP` | Koordinater kända, OK att placera på karta |
| `GND` | Minst en observatör (eller radar) på land |
| `CST` | Kustområde, möjligen strax utanför |
| `SEA` | Till sjöss, typiskt från fartyg |
| `AIR` | Luftburen observatör, ombord på flygplan |
| `MIL` | Minst en observatör militär |
| `CIV` | Minst en observatör civil |
| `HQO` | High Quality Observer — forskare, ingenjörer, tränade personer; eller 3+ personer med samstämmig beskrivning |

**Rad 2 — övriga detaljer**

| Kod | Betydelse |
|---|---|
| `SCI` | Vetenskapsman inblandad som observatör eller utredare; eller vetenskaplig provtagning |
| `TLP` | Telepati — tyst eller röstlös kommunikation |
| `NWS` | Rapport från nyhetsmedia, eller händelsen blev nyhet |
| `MID` | Sannolik misidentifiering av vardagligt objekt (Venus, raket …) |
| `HOX` | Misstanke om bluff, journalistiskt spratt |
| `CNT` | Contactee — kultledaraspiranter, återkommande "vittnen" med förutsägbara budskap |
| `ODD` | Oddity — mycket märklig händelse, atypisk avvikelse under händelsen, eller forteanska/paranormala drag |
| `WAV` | Del av en våg eller kluster av observationer |

**Rad 3 — typ av objekt**

| Kod | Betydelse |
|---|---|
| `SCR` | Klassisk tefat, disk, ovoid eller sfär — inte bara ett ljus |
| `CIG` | Torped, cigarr, flygkropp eller cylinder |
| `DLT` | Delta, V-form, bumerang, rektangulär; skarpa kanter och hörn |
| `NLT` | Nightlights — ljuspunkter utan urskiljbar form |
| `PRB` | Probe — litet objekt som manövrerar. Fjärrstyrt? |
| `FBL` | Fireball — flammande obestämd form, möjliga meteorer |
| `SUB` | Submersible — stiger ur eller sjunker ner i vatten |
| `NFO` | Inget farkostobjekt faktiskt sett |

**Rad 4 — entiteter**

| Kod | Betydelse |
|---|---|
| `OID` | Humanoid — mindre figur, ofta "grå" |
| `RBT` | Möjlig robot, kan likna "grå", mekaniska rörelser |
| `PSH` | Pseudo-human — möjlig klon eller robot; eller "människa" som arbetar med/för främmande figurer |
| `MIB` | Man-in-Black — PSH som utger sig för människa, eller mystisk man som försöker tysta rapporter |
| `MON` | Monster — livsform som inte passar någon standardkategori |
| `GNT` | Giant — större än de flesta människor |
| `FIG` | Odefinierad eller dåligt sedd figur, en skugga |
| `NOC` | Ingen entitet sedd |

**Rad 5 — aktiviteter**

| Kod | Betydelse |
|---|---|
| `OBS` | Observation, övervakning, förföljer/följer fordon |
| `RAY` | Märklig ljusstråle, sökarljus, laserliknande |
| `SMP` | Provtagning — växt, djur, jord, sten, vävnad |
| `MST` | Missing Time — oförklarat tidsglapp eller annan tidsanomali |
| `ABD` | Känd eller misstänkt bortförande av människa (även djur om hela) |
| `OPR` | Operationer på människor, djurmutilering, invasiv kirurgi |
| `SIG` | Indikation på signalering till/från/mellan objekt eller besättning, eller svar på mänskliga signaler |
| `CVS` | Conversation — all kommunikation mellan "oss" och "dem" |

**Rad 6 — platser och påverkan**

| Kod | Betydelse |
|---|---|
| `NUC` | Nukleär anläggning — kraftverk, militär, forskning |
| `DRT` | Jord påverkad — spår i mark, landningsmärken, fotspår |
| `VEG` | Växter påverkade eller provtagna, brutna grenar, sädesfältscirklar |
| `ANI` | Djur påverkade — panik, beteendeförändring, skador, märken |
| `HUM` | Människa påverkad — skada, brännmärken, psykologi, bortförande, dödsfall |
| `VEH` | Fordon påverkat — märken, brännskador, elektromagnetiska effekter |
| `BLD` | Byggnad eller annan konstruktion — vägar, broar, kraftledningar |
| `LND` | Landning — objektet (eller del av det) sätter sig ner |

**Rad 7 — bevis och särskilda effekter**

| Kod | Betydelse |
|---|---|
| `PHT` | Foto, film eller video |
| `RDR` | Anomala radarekon som motsvarar observationen |
| `RDA` | Strålning eller högenergifält uppmätt under eller efter |
| `EME` | Elektromagnetisk effekt — bil, radio, belysning, instrument |
| `TRC` | Fysiska spår, de flesta varianter |
| `TCH` | Tekniska detaljer, ledtrådar till främmande teknologi |
| `HST` | Historiskt vittnesmål, eller observationen blir historia |
| `INJ` | Sår, ärr, brännskador som följd av närkontakt; sjukdom, död, mutilering |

**Rad 8 — myndigheter och övrigt**

| Kod | Betydelse |
|---|---|
| `MIL` | Militär utredning — dold eller öppen, inhemsk eller utländsk |
| `BBK` | US Air Force BLUEBOOK-fall, oavsett slutsats |
| `GSA` | Government Security Agency — FBI, CIA, NSA, NRO, dolda säkerhetsorgan, inhemska och utländska |
| `OGA` | Other Government Agencies — polis, FAA, NASA, icke-dold myndighet |
| `SND` | Ljud hörda eller inspelade |
| `ODR` | Lukter associerade med objektet |
| `COV` | Indikation på officiell mörkläggning (inte enkel inkompetens) |
| `CMF` | Camouflage — försök att gömma eller förklä sig: molncigarrer, flygande bussar, falska kulisser |

> **Versionsvarning ur README.DOC:** i versioner före mars 2000 (serienummer ≤ 0307) hade rad 8 fälten `MIL BBK FBI CIA NSA OGA COV CMF`. Vår fil är senare (`Rec. #18120 EDITED`, README daterad 23AUG2003) och ska ha den nya uppsättningen — men verifiera mot data, och lagra vilken variant som gäller i modulens dokumentation.

`MIL` förekommer i både rad 1 (observatör militär) och rad 8 (militär utredning). Det är två olika attribut med samma mnemonic — därför måste `row` och `col` ingå i taxonomins nyckel, inte bara `code`.

---

## 8. Övriga fält som ska porteras

Ur manualen, utöver attributen:

| Fält | Beskrivning |
|---|---|
| `SUMMARY` | 78 tecken. Börjar alltid med platsen utskriven, t.ex. `MENLO PARK,CA:`. Kolon separerar features, kommatecken används i platsnamn. `CF` inskjutet betyder att koordinaterna är okända eller oprecisa |
| `DURATION` | 0–32000 minuter |
| `ELEVATION` | Observatörens höjd över havet i meter |
| `RELATIVE ALTITUDE` | Objektets höjd över/under observatören i meter |
| `TERRAIN` | Selection. Kända värden: METROPOLIS, TOWN, RESIDENTIAL, MILITARY, FARMLANDS, PASTURE, OIL & COAL, TUNDRA, DESERT, MOUNTAINS, WETLANDS, FOREST, RAINFOREST, COASTLANDS, OFFSHORE, HIGH SEAS, ISLANDS, IN-FLIGHT, SPACE, UNKNOWN, ROADS/RAILS. Extrahera fullständig lista ur manualen |
| `STRANGENESS` | 0–F hexadecimalt. Subjektiv "weirdness". Strukturlöst nattljus ≤ 5; poäng för landning, besättning, missing time |
| `CREDIBILITY` | 0–F hexadecimalt. Subjektiv. Ökar med fler och mer tränade vittnen |
| `REFERENCE` | Ref#-nummer. 93 = tidningar/fotnoter, 96–99 = övriga/ospecificerade, 97 = andra tidskrifter, 98 = andra böcker |
| `PAGE NUMBER` | 0–999. För tidskrifter anges nummer/volym i stället för sida |
| Kontinent / Land / Delstat | Mnemonic-koder, Appendix III och IV |

### `USOURCES.DOC` — källhänvisningarna

56 KB ren ASCII som mappar Ref# → full publiceringsdata. Detta ska porteras till en egen modell (`afu.larry_hatch.source` eller motsvarande) med `many2one` från fallposten. Det är precis den provenienskedja som gör arkivet trovärdigt för utomstående, och den ignoreras helt av det gamla scriptet.

### Raderade poster

Manualen: `[Delete]` markerar en post som överskrivbar genom att **sätta årtalet till 3000**. Poster med år 3000 är alltså logiskt raderade. Filtrera inte bort dem tyst — portera dem med en flagga `is_deleted`, så redovisningen blir sann mot källan.

---

## 9. Identitet och proveniens

**Använd inte postnumret som stabil nyckel.** Manualen är uttrycklig:

> *"*U* records are in strict chronological order. Record numbers will vary! Please refer to listings by Place, Date and Time instead."*

Postnummer ändras när Larry sorterar om filen eller lägger in nya fall.

**Lös det med en innehållshash** över de identitetsbärande fälten (datum, tid, koordinater, summary) — inte över hela posten, eftersom attributredigeringar då skulle ändra identiteten. Lagra hashen som `external_id` på **både** den porterade posten och senare på `uap.report`, så att de två sidorna är eniga om identiteten även efter en omsortering.

Behåll postnumret som ett separat, uttryckligen icke-stabilt fält (`source_record_no`) — det behövs för att kunna jämföra mot PDF:en och mot Larrys egna hänvisningar.

---

## 10. Faser

### Fas 1 — Fältspecifikation för `U.RND`

1. Parsa PDF:en till 18 122 ground-truth-poster med den korrigerade regexen.
2. Bygg brute-force-lösaren enligt avsnitt 5.
3. Lös de numeriska fälten mot 100 % matchgrad.
4. Lös kodfälten mot Appendix III/IV.
5. Lös attributbitarna via semantisk korrelation.
6. Skriv `docs/URND_format.md` med komplett byte-layout och matchgrad per fält.

**Leverans:** fältspecifikation med dokumenterad matchgrad. Osäkra fält uttryckligen listade.
**Detta är det enda steget som är oberoende av alla designval — börja här.**

### Fas 2 — Schemadesign

Definiera modellerna utifrån fältspecifikationen. Förslag på struktur:

| Modell | Syfte |
|---|---|
| `afu.larry_hatch.case` | fallposten, 1:1 mot `U.RND`-posten |
| `afu.larry_hatch.source` | Ref# → publiceringsdata ur `USOURCES.DOC` |
| `afu.attribute` | **delad** taxonomi, seedad med Larrys 64 koder (`code`, `name`, `row`, `col`, `archive`, `description`) |

`afu.attribute` ska vara delad mellan arkiven, inte Larry-specifik — det är i mappningen mellan olika källors kodsystem och en gemensam taxonomi som det analytiska värdet uppstår när nästa arkiv kommer.

Attributen kopplas med `many2many` från fallposten, inte som 64 booleska kolumner. Motivering: matrisen är exakt rekonstruerbar via `row`/`col`, sökbar generiskt i Odoo, och återanvändbar för nästa arkiv.

### Fas 3 — Modulen

Skapa `~/clio-odoo-addons/clio_afu_archives/` enligt `clio_uap`-konventionerna: `models/`, `views/`, `security/ir.model.access.csv`, `tests/`, `__manifest__.py`.

- `depends: ["base"]` — **inget mer**. Se avsnitt 1.
- Vyer som gör datat läsbart: list, form, sök med filter på attribut, år, land, strangeness/credibility. Kartvy om det går utan externa beroenden.
- Skapa Odoo-databasen `afu_archives` och installera modulen där. `uap`-databasen ska inte röras.

### Fas 4 — Portering och verifiering

1. Kör porteringen från `U.RND` → `afu.larry_hatch.case`.
2. Verifiera: antal = 18 122 (inklusive år-3000-poster). Jämför ett slumpurval på minst 200 poster fält för fält mot PDF:en.
3. Verifiera att attributfördelningen är rimlig — `NOC` (ingen entitet) ska vara mycket vanligare än `GNT` (jätte); `MAP` ska vara satt för i stort sett alla med kända koordinater.
4. Portera `USOURCES.DOC` och koppla Ref#.

**Leverans:** en Odoo-databas som går att bläddra i och som är trogen källan.

### Fas 5 — Plain export

Generera SQLite och/eller CSV ur den färdiga modellen, med samma schema. Detta är artefakten för mottagare som inte kör Odoo 19.

### Fas 6 — Mappning till `uap` — UTANFÖR DENNA PLAN

Görs i egen session, som eget granskat steg. Kort om vad som väntar där, så det inte byggs in fel antaganden tidigare:

- Mappningen är en **tolkning** — vilken attributkombination som ger `encounter_class`, vad som kvalificerar `intelligence_indicator`, vilka attribut som ger observables. Den ska skrivas ner, granskas och kunna köras om.
- Preliminär idé om mappningen (ej beslutad): `encounter_class` ur `LND`/`ABD`/`OPR`/`TRC`/`DRT`; `intelligence_indicator` ur `OID`/`RBT`/`PSH`/`MIB`/`MON`/`GNT`/`FIG` och `CVS`/`SIG`; `obs_transmedium` ur `SUB`; `obs_low_observability` ur `CMF`; `official_response` ur `MIL`/`BBK`/`GSA`/`OGA`/`COV`; `reporter_type` ur `MIL`/`CIV`/`HQO`/`SCI`; `shape` ur `SCR`/`CIG`/`DLT`/`NLT`/`PRB`/`FBL`; `uap.anomaly` ur `MST`/`TLP`/`ODD`.
- **Dubbletter är en öppen fråga.** Larry Hatch överlappar kraftigt med Blue Book, GEIPAN och Vallée-materialet som redan ligger i `uap` (65 150 encounters). Dedupliceringsstrategin behöver egen genomgång — `uap.report.canonical_id` och `duplicate_ids` finns för det.

---

## 11. Fallgropar i `uap`-modellerna (för fas 6, men bra att känna till)

Fem buggar hittades i det gamla `afu_import.py`. De tre första gäller `uap`-modellerna och kommer tillbaka i fas 6:

1. **Selection-fält tar strängar, inte heltal.** `discourse_level`, `eth_origin`, `intelligence_indicator`, `encounter_class` är alla `selection` med strängvärden. `{"discourse_level": 2}` ger `ValueError: Wrong value for uap.encounter.discourse_level: 2`. Det var detta som fick hela originalimporten att krascha. Skicka `"2"`.
2. **`uap.encounter.encounter_id` är ett obligatoriskt `char`-fält** — ett läsbart ID, inte en relation. Konvention i befintlig data: `<KÄLLA>_<LANDKOD>_<ÅR>_<8 hex>`, t.ex. `NUFORC_GB_2024_5d36957a`, `PURSUE_XXXX_02e5b5cf`. Det gamla scriptet satte det aldrig. Ingen unique-constraint finns, bara främmandenycklar — men generera deterministiskt ändå, så importen blir idempotent.
3. **`uap.report.status` är inte beräknat.** Att skriva `encounter_id` sätter *inte* `status` till `linked` automatiskt — verifierat. Sätt båda explicit.
4. **Dedupliceringen måste ta hänsyn till `encounter_id`.** Originalscriptet ansåg varje report med rätt `import_batch` som redan importerad, oavsett om den hade någon encounter. Resultatet: 9 225 föräldralösa reports blockerade permanent varje ny körning med "0 nya att skapa". Filtrera på `["encounter_id", "!=", False]`.
5. **Härled ingenting ur precisionskoden.** Se avsnitt 6.

---

## 12. Tillstånd i `uap`-databasen just nu

Åtgärdat 2026-09-26:

- De 9 225 föräldralösa `uap.report`-posterna med `import_batch = larry_hatch_afu_20260925` är **raderade**. `uap.report` gick från 117 247 till 108 022. Backup: `~/19.0/clio-tools/clio-afu/data/backup_orphaned_reports_larry_hatch_afu_20260925.json` (5,4 MB).
- `uap.encounter` orörd: 65 150 poster. Inga encounters från Larry Hatch fanns eller finns.
- `uap.database` id=40 heter `"Larry Hatch *U* Database — AFU derivation"`. Namnet beskriver PDF-derivationen. Porterar vi från `U.RND` bör originalet registreras i stället, annars pekar proveniensen på fel artefakt.
- De 29 614 övriga `uap.report` utan encounter är **inte** samma problem — de saknar `import_batch` helt och `status` stämmer överens med `encounter_id` (78 408 `linked` / 29 614 `unlinked`). Det är stagingbackloggen som väntar på länkning, enligt design. Rör dem inte.
- `afu_import.py` är oförändrad på servern. Backup: `afu_import.py.bak-20260926`.

---

## 13. Att börja med

```bash
ssh clioadmin@100.107.127.104
cd ~/19.0/clio-tools/clio-afu
```

Första uppgiften är fas 1, steg 1–3: parsa PDF:en till ground truth och lös de numeriska byteoffsetarna. Det kräver inga designbeslut och ger den fältspecifikation som allt annat hänger på.
