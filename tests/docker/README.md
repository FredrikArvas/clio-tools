# clio-tools Docker-test

## Syfte

Verifiera att `requirements.txt` installeras korrekt på Linux och att
unit-testerna passerar i en ren miljö — oberoende av lokal maskin.

Löser problemet med "works on my machine": saknade paket i requirements.txt
upptäcks direkt eftersom Docker-imagen startar helt tom.

## Köra testet

Från repo-roten (`clio-tools/`):

```bash
# Normal körning — bygger, testar, kastar imagen
bash tests/docker/run_install_test.sh

# Behåll imagen för felsökning
bash tests/docker/run_install_test.sh --keep

# Öppna shell inuti containern
bash tests/docker/run_install_test.sh --shell
```

## Vad testas

| Steg | Vad |
|------|-----|
| `apt-get install` | Systempaket (tesseract, ghostscript, ffmpeg, exiftool) |
| `pip install -r requirements.txt` | Alla Python-paket — fångar saknade entries |
| `python clio_qc.py` | Syntax, TUI-mönster, beroendekontroll |
| `python tests/run_tests.py` | Alla unit-tester (333 st) |

## Vad testas INTE här (Steg 3)

- Qdrant / RAG-pipeline
- Odoo / clio-agent-odoo
- SMTP / clio-agent-mail
- GPU / Whisper-transkribering

Dessa kräver `docker-compose` med externa tjänster och sätts upp separat.

## Felsökning

Om bygget misslyckas vid `pip install`:
```bash
# Starta ett rent Python-skal och installera manuellt
docker run --rm -it python:3.12-slim bash
pip install <problematiskt-paket>
```

Om ett unit-test misslyckas:
```bash
bash tests/docker/run_install_test.sh --keep
docker run --rm -it clio-tools-test bash
python tests/run_tests.py -v
```
