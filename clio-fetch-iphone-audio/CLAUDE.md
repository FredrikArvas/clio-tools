# clio-fetch-iphone-audio — CLAUDE.md

## Syfte
Hämtar WAV-filer från AudioShare på iPhone över lokalt nätverk till angiven mapp på datorn.

## Status
Aktiv

## Snabbstart
```powershell
python main.py
python main.py --dry-run
python main.py --host 192.168.1.214 --dest "C:/Users/fredr/Dropbox/Audio/iPhone-inspelningar"
python main.py --probe          # Testa vilken URL-mall som fungerar
```

## Nyckelkod
- `main.py` — AudioShare HTTP-klient, filhämtning

## Beroenden
Externa: requests
Interna: clio-core

## Relaterade moduler
clio-core, clio-audio-edit, clio-transcribe

## Gotchas
Standard-IP: 192.168.1.214. Chunk-storlek 65KB, timeout 15s (lista) / 300s (filer). Testar flera URL-mallar vid auto-probe om standardmallen inte fungerar.
