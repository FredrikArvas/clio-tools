# clio_music — PHP-musikspelare

Enkel musikspelarsida för cPanel-webbhotell. Inga ramverk, ingen databas.

## Driftsättning via FTP

Ladda upp dessa filer till din webbhotells public_html (eller valfri mapp):

```
index.php
player.js
style.css
config.php
music/   ← tom mapp, lägg dina MP3-filer här
```

## Lägga till musik

Kopiera MP3-filer till `/music/` via FTP. Nästa sidhämtning visar dem automatiskt.  
Filnamnet används som låttitel om ID3v1-metadata saknas (understreck/bindestreck → mellanslag).

## Konfigurera

Redigera `config.php`:

```php
$music_dir  = __DIR__ . '/music';   // sökväg till musikmappen på servern
$music_url  = 'music';              // URL-prefix relativt index.php
$site_title = 'Musik';              // visas i rubrik och flikens titel
```

## Krav

- PHP 7.4+ (standard på alla moderna cPanel-hotell)
- Inga tillägg att installera
