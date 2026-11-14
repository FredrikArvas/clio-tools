<#
ncc_sync.ps1 — Genererar ~/.claude/ncc-codes.md från Projektmasterlistan

Källa: clio-service på EliteDesk (/mail/ncc/lista/json) — samma endpoint som
Odoo-modulen clio_ncc_project använder vid "Ladda om". Notion förblir master.

Kör:  powershell -File ncc_sync.ps1
      powershell -File ncc_sync.ps1 -NoRefresh        # använd clio-service-cache
      powershell -File ncc_sync.ps1 -Out C:\annan\fil.md

Filen skrivs bara om om hämtningen lyckas och ger minst -MinRows rader.
#>
param(
    [string]$ServiceUrl = "http://100.107.127.104:7200",
    [string]$Out        = (Join-Path $env:USERPROFILE ".claude\ncc-codes.md"),
    [int]$MinRows       = 10,
    [switch]$NoRefresh
)

$ErrorActionPreference = "Stop"

# ── Hämta ──────────────────────────────────────────────────────────────────────
# Invoke-WebRequest + egen UTF-8-avkodning: PS 5.1 gissar annars Latin-1.
$body = if ($NoRefresh) { '{"refresh":false}' } else { '{"refresh":true}' }
$resp = Invoke-WebRequest -Uri "$ServiceUrl/mail/ncc/lista/json" -Method Post `
    -Body $body -ContentType "application/json" -TimeoutSec 60 -UseBasicParsing
$json = [Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray()) | ConvertFrom-Json

if (-not $json.ok) { throw "clio-service svarade ok=false: $($json.error)" }

# ── Filtrera ───────────────────────────────────────────────────────────────────
$rows = $json.projects |
    Where-Object { $_.kodord -and $_.ncc_page_id } |
    Sort-Object { $_.kodord.Trim().ToLower() } -Unique

if ($rows.Count -lt $MinRows) {
    throw "Bara $($rows.Count) kodord med NCC (min $MinRows) — skriver inte över $Out"
}

$missing = $json.projects | Where-Object { $_.kodord -and -not $_.ncc_page_id }

# ── Skriv ──────────────────────────────────────────────────────────────────────
$now = Get-Date -Format "yyyy-MM-dd HH:mm"
$lines = @(
    "# NCC-kodord → Context Card (Notion page-ID)",
    "",
    "Genererad $now av clio-tools/ncc_sync.ps1 — redigera inte för hand.",
    "Hämta med notion-fetch på ID:t. Nytt kodord: lägg rad i Projektmasterlistan (Notion) och kör ncc_sync.ps1.",
    "",
    "| Kodord | Nr | Projekt | Page-ID |",
    "|---|---|---|---|"
)
foreach ($p in $rows) {
    $name = ($p.name -replace '\|', '/').Trim()
    $lines += "| $($p.kodord.Trim().ToLower()) | $($p.nr) | $name | $($p.ncc_page_id -replace '-', '') |"
}
if ($missing) {
    $lines += ""
    $lines += "Kodord utan NCC: " + (($missing | ForEach-Object { $_.kodord.Trim().ToLower() } | Sort-Object -Unique) -join ", ")
}

# Atomisk skrivning: temp-fil först, sedan ersätt.
$tmp = "$Out.tmp"
[IO.File]::WriteAllText($tmp, ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))
Move-Item -Force $tmp $Out

Write-Output "ncc_sync: $($rows.Count) kodord → $Out"
