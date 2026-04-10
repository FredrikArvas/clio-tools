# clio-install

Installationsscript och avinstallationsscript för clio-tools-ekosystemet.

## Användning

```powershell
# Från clio-tools-roten
python clio-install/install.py

# Med auto-bekräftelse (agent-läge)
python clio-install/install.py --yes

# Torrkörning — se vad som skulle göras
python clio-install/install.py --dry-run

# Avinstallera (läser install_log.json)
python clio-install/uninstall.py
```

## Vad installern gör

**Steg 1 — Systemprogram**
Kontrollerar Python, Git, exiftool, Ollama, Tesseract OCR och DigiKam.
- Erbjuder installation via `winget` för tillgängliga paket
- Exiftool: letar efter lokal kopia i `clio-vision/exiftool-13.54_64/`
- Ollama: frågar om llava-modellen (~4 GB) ska laddas ned

**Steg 2 — Python-paket**
Installerar alla pip-beroenden för hela ekosystemet.

**Steg 3 — clio-core**
Installerar det gemensamma kärnpaketet i editable mode (`pip install -e`).

**Steg 4 — Miljövariabler**
Skapar `.env`-stub om den saknas. Du fyller i `ANTHROPIC_API_KEY` manuellt.

## Idempotent

Installern kan köras om hur många gånger som helst utan att dubbelinstallera.
Kör igen efter att uppskjutna beroenden (t.ex. Ollama) är hanterade.

## install_log.json

Alla åtgärder loggas i `clio-install/install_log.json`.
Filen är maskinläsbar och används av `uninstall.py` för att ångra installationen.

## Begränsningar

- PATH-ändringar via Windows Registry kräver ny terminal för att gälla
- Systemprogram installerade via winget avinstalleras **inte** automatiskt —
  `uninstall.py` visar instruktion för manuell avinstallation
- Pip-paket som även används av andra program avinstalleras med varning
- `winreg` används för PATH-manipulation och kräver Windows
