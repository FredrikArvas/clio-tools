# Clio Tools – UAT-checklista

Fyll i version och datum. Kryssa av varje punkt manuellt innan release.

**Version:** vX.Y.Z
**Datum:**
**Testat av:**

---

## Miljö

- [ ] `python tests/run_tests.py --all` – alla tester gröna
- [ ] `python config/clio_check.py` – miljön rapporterar OK

---

## clio-docs

- [ ] Kör mot en mapp med en skannad PDF
- [ ] Fråga om undermappar visas om det finns PDF:er i undermappar
- [ ] `_OCR.pdf` skapas och är sökbar (ctrl+F i PDF-läsare)
- [ ] `_OCR.md` skapas med sidrubriker (`## Page 1`, `## Page 2` etc.)
- [ ] Redan OCR:ade filer hoppas över (kör igen – ska säga "Skipping")
- [ ] Loggfil `clio-docs-batch.log` uppdateras

---

## clio-vision

- [ ] Välj Claude-motor (kräver `ANTHROPIC_API_KEY`)
- [ ] Kostnadsfråga visas med uppskattat belopp, svara J
- [ ] `_VISION.md` skapas med `description`, `tags`, `## Master data`
- [ ] Kör igen – filen hoppas över ("Skipping")
- [ ] (Valfritt) Välj Ollama om det körs lokalt

---

## clio-transcribe

- [ ] Kör mot en mapp med en MP3/WAV på svenska
- [ ] Modell laddas (KB-Whisper för sv)
- [ ] `_TRANSKRIPT.md` skapas med tidsstämplar (`**[00:00 → 00:05]**`)
- [ ] Detekterat språk loggas med sannolikhet
- [ ] Kör igen – filen hoppas över

---

## clio-narrate

- [ ] Välj Edge-TTS, röst Sofie, hastighet Normal
- [ ] `_NARRAT.mp3` skapas
- [ ] Filen spelas upp korrekt med ett mediaplayer
- [ ] ID3-taggar syns (titel, artist) i mediaspelaren
- [ ] Kör igen – filen hoppas över

---

## clio-fetch

- [ ] `python clio-fetch/clio_fetch.py --url https://example.com`
- [ ] JSON sparas i `output/`, filnamn innehåller domännamn + tidsstämpel
- [ ] JSON innehåller `title`, `text`, `word_count`, `source`, `fetched_at`
- [ ] `python clio-fetch/clio_fetch.py --dir <sökväg till httrack-mapp>`
- [ ] Flera JSON-filer skapas, namngivning speglar URL-strukturen
- [ ] Sammanfattningsrad visar totalt antal filer

---

## clio-emailfetch

- [ ] `python clio-emailfetch/imap_backup.py` – inga IMAP-fel
- [ ] Nya `.eml`-filer hamnar i rätt mapp under Dropbox
- [ ] `backup_state.json` uppdateras

---

## Meny (clio.py)

- [ ] `python clio.py` startar utan fel
- [ ] Alla 7 verktyg syns med beskrivning
- [ ] Menyval 7 (clio-fetch) visar usage-dokumentation och avslutar
- [ ] `c` kör `clio_check` utan fel
- [ ] `q` avslutar utan fel
- [ ] Senaste körning markeras med ◀ vid nästa start

---

## Signatur

Testad och godkänd: ___________________  Datum: ___________
