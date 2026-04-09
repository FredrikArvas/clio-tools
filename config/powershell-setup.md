# PowerShell-konfiguration för Clio Tools
Version 1.0 | April 2026

---

## Problemet

PowerShell på Windows använder cp1252 som default-encoding.
Det gör att UTF-8-filer (t.ex. JSON med svenska tecken) visas fel:
`Ã¤` istället för `ä`, `Ã¥` istället för `å` osv.

---

## Lösning – konfigurera profilen

### Steg 1: Hitta din profil

```powershell
$PROFILE
```

Visar sökvägen, t.ex.:
`C:\Users\fredr\Documents\PowerShell\Microsoft.PowerShell_profile.ps1`

### Steg 2: Öppna profilen

```powershell
notepad $PROFILE
```

Om filen inte finns skapar Notepad den. Bekräfta om du får en dialogruta.

### Steg 3: Lägg till dessa rader

```powershell
# ── Clio Tools: UTF-8 som default ────────────────────────────────
$PSDefaultParameterValues['*:Encoding'] = 'utf8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
```

### Steg 4: Ladda om profilen

```powershell
. $PROFILE
```

---

## Verifiering

Kör detta för att bekräfta att det fungerar:

```powershell
# Ska visa: ä å ö – inte Ã¤ Ã¥ Ã¶
Get-Content ".\output\gtff.se_2017-01-04_nya-hemsidan-lanserad_*.json" | Select-Object -First 3
```

---

## Engångskommando (utan profil)

Om du inte vill ändra profilen, kör detta i varje ny session:

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

Eller lägg till `-Encoding UTF8` på enskilda kommandon:

```powershell
Get-Content "fil.json" -Encoding UTF8
```

---

## Notering om pip och Python

Python på Windows skriver ibland till stdout med cp1252 trots UTF-8-innehåll.
Om du ser konstiga tecken i terminalen från Python-scripts, starta sessionen med:

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

Eller lägg till den raden i profilen tillsammans med ovanstående.
