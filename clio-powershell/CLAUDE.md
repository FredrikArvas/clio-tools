# clio-powershell — CLAUDE.md

## Syfte
Konfigurationsguide för PowerShell UTF-8-encoding. Löser cp1252→UTF-8-problemet med JSON och svenska tecken i Windows-terminalen.

## Status
Dokumentation

## Snabbstart
```powershell
# Engångsfix i PowerShell-profilen ($PROFILE):
$PSDefaultParameterValues['*:Encoding'] = 'utf8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8

# Eller per session:
$env:PYTHONIOENCODING = "utf-8"
```

## Nyckelkod
- `powershell-setup.md` — Fullständig UTF-8 setup-guide

## Beroenden
Externa: Inga
Interna: Ingen

## Relaterade moduler
Relevant för alla moduler körda från PowerShell på Windows

## Gotchas
Windows defaultar till cp1252 — måste ändras för att svenska tecken ska visas korrekt i Python-output.
