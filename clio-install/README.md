# clio-install

Installationsscript och avinstallationsscript för clio-tools-ekosystemet.

---

## Maskinöverflyttning

### Från-maskin (befintlig installation)

```powershell
# 1. Exportera .env och clio.config krypterat
python clio-install/env_transfer.py --export
# → sparar clio-env-transfer.zip på Skrivbordet

# 2. Kopiera zip manuellt till målmaskinen (USB, nätverksdelning m.m.)
```

### Till-maskin (ny maskin med befintliga inställningar)

```powershell
# 1. Klona repot
git clone https://github.com/FredrikArvas/clio-tools.git
cd clio-tools

# 2. Importera .env och clio.config från zip
python clio-install/env_transfer.py --import clio-env-transfer.zip

# 3. Installera och verifiera
python clio-install/install.py --venv --yes --check
```

### Ny installation (ingen zip att importera)

```powershell
# 1. Klona repot
git clone https://github.com/FredrikArvas/clio-tools.git
cd clio-tools

# 2. Installera och verifiera
python clio-install/install.py --venv --yes --check
# → .env-stub skapas automatiskt — fyll i ANTHROPIC_API_KEY manuellt
```

---

## Övriga kommandon

```powershell
# Interaktiv installation (frågar vid varje steg)
python clio-install/install.py

# Torrkörning — se vad som skulle göras utan att installera
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
