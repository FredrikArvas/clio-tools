# clio-narrate

Text-till-tal: konverterar `.txt`, `.md` och `.docx`-filer till MP3. Stöder tre motorer med olika avvägning mellan kostnad och kvalitet.

## Körning

```powershell
python clio-narrate-batch.py <fil-eller-mapp>
python clio-narrate-batch.py <fil> --engine edge    # Microsoft Edge TTS (standard)
python clio-narrate-batch.py <fil> --engine piper   # Lokal Piper (gratis, svenska)
python clio-narrate-batch.py <fil> --engine eleven  # ElevenLabs (bäst kvalitet)
```

**Utdata:** `filnamn_NARRAT.mp3`

## Motorer

| Motor | Kostnad | Krav |
|---|---|---|
| Piper | Gratis, offline | Ladda ned röstmodell |
| Edge-TTS | Gratis, online | Internet |
| ElevenLabs | Betald | `ELEVENLABS_API_KEY` i `.env` |

## Beroenden

```powershell
pip install -r requirements.txt
python check_deps.py
```
