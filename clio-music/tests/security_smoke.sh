#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>
# security_smoke.sh — säkerhetsrökttest för clio_music.
#
# Körs PÅ SERVERN (curl mot nginx på 127.0.0.1:8091, förbi Cloudflare):
#   bash tests/security_smoke.sh
#
# Rör aldrig produktionsdata: inloggade tester använder en tillfällig sessionsfil för den
# fiktiva användaren __smoketest__ (skapas med sudo i PHP:s session.save_path och raderas
# vid avslut). users.csv, profiler och spelloggen skrivs inte.
#
# Testdata (spårnamn/grupper) speglar prod-katalogen; uppdatera här om spåren byts ut.

set -u

BASE="${BASE:-http://127.0.0.1:8091}"
SESSION_DIR="${SESSION_DIR:-/var/lib/php/sessions}"
COOKIE_NAME="${COOKIE_NAME:-PHPSESSID}"

GUEST_TRACK="Välkommen till FrUlleBo.mp3"      # grupp Gäst
GUEST_LYRICS="Välkommen till FrUlleBo.lrc"
GUEST_TRACK_URL="music/Välkommen%20till%20FrUlleBo.mp3"
PRIVATE_CHANNEL="001_mediation_vce.mp3"        # grupp RIM1, kanalfil (huvudfil _msc)
OTHER_GROUP_TRACK="Guldbodapolka 2026.mp3"     # grupp Guldbodalåtar
PRIVATE_LYRICS="demo_jatten_01.lrc"            # spåret har en icke-gästgrupp
# Spår utan grupp (synligt för alla inloggade, aldrig för gäster) letas upp dynamiskt, eftersom
# admin kan flytta spår mellan grupper. Finns inget hoppas de kontrollerna över.
WEBROOT="${WEBROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
# Körs som www-data: data/track_groups.csv är 640 www-data:www-data (S6) och kan inte läsas av clioadmin.
UNGROUPED_TRACK=$(cd "$WEBROOT" && sudo -u www-data php -r 'require "access.php"; $map = load_track_groups();
    foreach (scan_music("music")["standalone"] as $f) { if (track_group($f, $map) === "") { echo $f; break; } }')
TEST_GROUP="RIM1"

pass=0; fail=0; session_files=()

encode() { php -r 'echo rawurlencode($argv[1]);' "$1"; }

# check <beskrivning> <förväntade koder, t.ex. "403|404"> <curl-argument...>
check() {
    local description="$1" expected="$2"; shift 2
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' "$@")
    if [[ "$code" =~ ^($expected)$ ]]; then
        pass=$((pass + 1)); printf '  OK    %-62s %s\n' "$description" "$code"
    else
        fail=$((fail + 1)); printf '  FEL   %-62s %s (väntat %s)\n' "$description" "$code" "$expected"
    fi
}

# check_header <beskrivning> <regex> <curl-argument...> — kollar svarshuvudena
check_header() {
    local description="$1" pattern="$2"; shift 2
    if curl -s -o /dev/null -D - "$@" | grep -qiE "$pattern"; then
        pass=$((pass + 1)); printf '  OK    %s\n' "$description"
    else
        fail=$((fail + 1)); printf '  FEL   %s (saknar /%s/)\n' "$description" "$pattern"
    fi
}

# Skapar en sessionsfil för __smoketest__ med given grupp och skriver ut sessions-id:t.
# Andra argumentet (valfritt) är 1 för en admin-session, annars 0.
make_session() {
    local group="$1" is_admin="${2:-0}" id
    id="smoke$(openssl rand -hex 16)"
    php -r '
        $user = ["username" => "__smoketest__", "display" => "Smoketest", "admin" => (int)$argv[2], "groups" => [$argv[1]]];
        $now  = time();
        echo "cm_user|" . serialize($user) . "cm_created|" . serialize($now) . "cm_last_seen|" . serialize($now);
    ' "$group" "$is_admin" | sudo tee "$SESSION_DIR/sess_$id" > /dev/null
    sudo chown www-data:www-data "$SESSION_DIR/sess_$id"
    sudo chmod 600 "$SESSION_DIR/sess_$id"
    session_files+=("$SESSION_DIR/sess_$id")
    echo "$id"
}

cleanup() { for f in "${session_files[@]}"; do sudo rm -f "$f"; done; }
trap cleanup EXIT

music()  { echo "$BASE/music/$(encode "$1")"; }
lyrics() { echo "$BASE/lyrics/$(encode "$1")"; }

echo "== S1: mediaåtkomst som gäst (T2/T3)"
check "gäst: gästspår"                         "200" "$(music "$GUEST_TRACK")"
check "gäst: gästspår med Range → 206"         "206" -r 0-99 "$(music "$GUEST_TRACK")"
check "gäst: gästspårets lyrics"               "200" "$(lyrics "$GUEST_LYRICS")"
check "gäst: privat kanalfil (T2)"             "403" "$(music "$PRIVATE_CHANNEL")"
if [[ -n "$UNGROUPED_TRACK" ]]; then
    check "gäst: spår utan grupp"              "403" "$(music "$UNGROUPED_TRACK")"
else
    echo "  --    gäst: spår utan grupp (inget sådant spår finns, överhoppat)"
fi
check "gäst: lyrics till privat spår (T3)"     "403" "$(lyrics "$PRIVATE_LYRICS")"
check_header "mp3: Content-Type audio/mpeg"         '^content-type: audio/mpeg' "$(music "$GUEST_TRACK")"
# Cachning (v1.8.0): gästspår är publika och får cachas av Cloudflare i en vecka.
# Nekade svar får aldrig cachas.
check_header "gästspår: Cache-Control public, max-age=604800" '^cache-control: public, max-age=604800' "$(music "$GUEST_TRACK")"
check_header "nekat svar (403): Cache-Control private, no-store" '^cache-control: private, no-store' "$(music "$PRIVATE_CHANNEL")"
if curl -s -o /dev/null -D - "$(music "$GUEST_TRACK")" | grep -qi '^x-accel-redirect'; then
    fail=$((fail + 1)); echo "  FEL   X-Accel-Redirect läcker till klienten"
else
    pass=$((pass + 1)); echo "  OK    X-Accel-Redirect läcker inte till klienten"
fi

echo "== S1: sökvägsmanipulation"
# nginx avkodar och normaliserar "..%2f" före location-matchningen: /music/..%2fdata%2fx blir
# /data/x och träffar data-spärren (403). Det viktiga är att filen aldrig levereras.
check "traversal ..%2fdata%2fusers.csv"        "400|403|404" "$BASE/music/..%2fdata%2fusers.csv"
check "dubbelkodad traversal"                  "400|403|404" "$BASE/music/..%252fconfig.php"
check "traversal lyrics → data/users.csv"      "400" "$BASE/lyrics/..%2f..%2fdata%2fusers.csv"
check "fel filändelse x.php"                   "400" "$BASE/music/x.php"
check "katalogen /music/"                      "400" "$BASE/music/"
check "punktfil"                               "400" "$BASE/music/.hidden.mp3"
check "okänd fil"                              "404" "$BASE/music/finns_inte.mp3"
check "intern location direkt"                 "404" "$BASE/_protected/music/$(encode "$GUEST_TRACK")"
check "POST mot media"                         "405" -X POST "$(music "$GUEST_TRACK")"

echo "== S1: mediaåtkomst inloggad (grupp $TEST_GROUP)"
session_id=$(make_session "$TEST_GROUP")
cookie=(-b "$COOKIE_NAME=$session_id")
check "inloggad: egen grupps kanalfil"         "200" "${cookie[@]}" "$(music "$PRIVATE_CHANNEL")"
check "inloggad: Range → 206"                  "206" "${cookie[@]}" -r 0-99 "$(music "$PRIVATE_CHANNEL")"
# Spår som inte är gästspår cachas bara i webbläsaren, aldrig av delade cachar (Cloudflare).
check_header "privat spår: Cache-Control private, max-age=604800" '^cache-control: private, max-age=604800' "${cookie[@]}" "$(music "$PRIVATE_CHANNEL")"
check_header "privat spår: Vary: Cookie"            '^vary: .*cookie' "${cookie[@]}" "$(music "$PRIVATE_CHANNEL")"
if [[ -n "$UNGROUPED_TRACK" ]]; then
    check "inloggad: spår utan grupp"          "200" "${cookie[@]}" "$(music "$UNGROUPED_TRACK")"
else
    echo "  --    inloggad: spår utan grupp (inget sådant spår finns, överhoppat)"
fi
check "inloggad: annan grupps spår"            "403" "${cookie[@]}" "$(music "$OTHER_GROUP_TRACK")"

echo "== S2: sessionscookie (T7/T10)"
check_header "cookie HttpOnly"                      '^set-cookie: .*httponly' "$BASE/login.php"
check_header "cookie SameSite=Lax"                  '^set-cookie: .*samesite=lax' "$BASE/login.php"
check_header "cookie Secure bakom HTTPS-proxy"      '^set-cookie: .*secure' -H 'X-Forwarded-Proto: https' "$BASE/login.php"
# use_strict_mode: ett påhittat sessions-id ska ersättas av ett nytt från servern.
fixated="smokefixation$(openssl rand -hex 8)"
if curl -s -o /dev/null -D - -b "$COOKIE_NAME=$fixated" "$BASE/login.php" | grep -qi "^set-cookie: $COOKIE_NAME=" \
   && ! curl -s -o /dev/null -D - -b "$COOKIE_NAME=$fixated" "$BASE/login.php" | grep -qi "^set-cookie: $COOKIE_NAME=$fixated"; then
    pass=$((pass + 1)); echo "  OK    påhittat sessions-id avvisas (strict mode)"
else
    fail=$((fail + 1)); echo "  FEL   påhittat sessions-id accepteras (session fixation)"
fi

echo "== S2: inloggning (T6) — fiktivt konto, riktiga konton rörs inte"
test_start=$(date +%s)
jar=$(mktemp)
login_token() { curl -s -c "$jar" -b "$jar" "$BASE/login.php" | grep -o 'name="csrf_token" value="[^"]*"' | sed 's/.*value="//;s/"$//'; }
bf_user="__smoketest_bf_$(openssl rand -hex 4)"
check "POST login utan CSRF-token"             "403" -X POST -d "username=$bf_user&password=x" "$BASE/login.php"
token=$(login_token)
start_ms=$(date +%s%3N)
check "okänt namn, fel lösenord"               "200" -c "$jar" -b "$jar" --data-urlencode "csrf_token=$token" -d "username=$bf_user&password=fel" "$BASE/login.php"
elapsed=$(( $(date +%s%3N) - start_ms ))
if (( elapsed >= 100 )); then
    pass=$((pass + 1)); echo "  OK    okänt namn kör password_verify (${elapsed} ms)"
else
    fail=$((fail + 1)); echo "  FEL   okänt namn svarar för snabbt (${elapsed} ms) — användaruppräkning möjlig"
fi
for attempt in 2 3 4 5; do
    curl -s -o /dev/null -c "$jar" -b "$jar" --data-urlencode "csrf_token=$token" -d "username=$bf_user&password=fel$attempt" "$BASE/login.php"
done
check "6:e försöket spärras"                   "429" -c "$jar" -b "$jar" --data-urlencode "csrf_token=$token" -d "username=$bf_user&password=fel6" "$BASE/login.php"

echo "== S2: utloggning"
check "GET logout loggar inte ut (bara knapp)" "200" "${cookie[@]}" "$BASE/logout.php"
check "POST logout utan token"                 "403" "${cookie[@]}" -X POST "$BASE/logout.php"
logout_token=$(curl -s "${cookie[@]}" "$BASE/logout.php" | grep -o 'name="csrf_token" value="[^"]*"' | sed 's/.*value="//;s/"$//')
check "POST logout med token → redirect"       "302" "${cookie[@]}" --data-urlencode "csrf_token=$logout_token" "$BASE/logout.php"
if sudo test -f "$SESSION_DIR/sess_$session_id"; then
    fail=$((fail + 1)); echo "  FEL   sessionsfilen finns kvar efter utloggning"
else
    pass=$((pass + 1)); echo "  OK    sessionsfilen raderad vid utloggning"
fi
check "gammal cookie efter utloggning"         "403" "${cookie[@]}" "$(music "$PRIVATE_CHANNEL")"

echo "== S4: admin-sidor (T5) — bara anrop som avvisas innan något skrivs"
check "hash_tool.php är borttaget"                "403|404" "$BASE/admin/hash_tool.php"
user_session=$(make_session "$TEST_GROUP")
admin_session=$(make_session "$TEST_GROUP" 1)
# make_session körs i en underskal, så dess egen städlista går förlorad: registrera filerna här.
session_files+=("$SESSION_DIR/sess_$user_session" "$SESSION_DIR/sess_$admin_session")
user_cookie=(-b "$COOKIE_NAME=$user_session")
admin_cookie=(-b "$COOKIE_NAME=$admin_session")
check "icke-admin: GET groups.php"                 "403" "${user_cookie[@]}" "$BASE/admin/groups.php"
check "icke-admin: POST groups.php (med token)"    "403" "${user_cookie[@]}" -X POST -d "save_users=1" "$BASE/admin/groups.php"
check "admin: GET groups.php"                      "200" "${admin_cookie[@]}" "$BASE/admin/groups.php"
check "admin: GET groups.php?tab=tracks"           "200" "${admin_cookie[@]}" "$BASE/admin/groups.php?tab=tracks"
check "admin: POST utan CSRF-token (users)"        "403" "${admin_cookie[@]}" -X POST -d "save_users=1" "$BASE/admin/groups.php?tab=users"
check "admin: POST utan CSRF-token (tracks)"       "403" "${admin_cookie[@]}" -X POST -d "save_tracks=1" "$BASE/admin/groups.php?tab=tracks"
check "admin: POST med fel CSRF-token"             "403" "${admin_cookie[@]}" -X POST -d "save_users=1&csrf_token=fel" "$BASE/admin/groups.php"
admin_token=$(curl -s "${admin_cookie[@]}" "$BASE/admin/groups.php" | grep -o 'name="csrf_token" value="[^"]*"' | tail -1 | sed 's/.*value="//;s/"$//')
# "Lägg till grupp" skriver aldrig något, så ogiltiga namn kan provas säkert mot prod.
for bad_name in 'a;b' 'a|b' 'a"b' $'a\nb' "$(printf 'x%.0s' $(seq 1 200))"; do
    check "ogiltigt gruppnamn avvisas: $(printf '%q' "${bad_name:0:12}")" "400" "${admin_cookie[@]}" \
        --data-urlencode "csrf_token=$admin_token" --data-urlencode "new_group_name=$bad_name" -d "add_group=1" "$BASE/admin/groups.php"
done
check "giltigt gruppnamn accepteras (skriver inget)" "200" "${admin_cookie[@]}" \
    --data-urlencode "csrf_token=$admin_token" --data-urlencode "new_group_name=Smoke test" -d "add_group=1" "$BASE/admin/groups.php"

echo "== S3: API-validering (T8) — giltiga anrop skriver bara för __smoketest__"
PROFILE_TRACK_URL="music/${PRIVATE_CHANNEL/_vce/_msc}"   # huvudfilen i flerkanalsspåret
api_session=$(make_session "$TEST_GROUP")
session_files+=("$SESSION_DIR/sess_$api_session")
api_cookie=(-b "$COOKIE_NAME=$api_session")
page_token() { grep -o '"CM_CSRF":"[^"]*"' | sed 's/.*:"//;s/"$//'; }   # JSON-blocket cm-data i index.php (S5)
api_token=$(curl -s "${api_cookie[@]}" "$BASE/" | page_token)
json=(-H 'Content-Type: application/json')
csrf=(-H "X-CSRF-Token: $api_token")
valid_profile="{\"track\":\"$PROFILE_TRACK_URL\",\"settings\":{\"msc\":0.55,\"bass\":-2,\"liked\":true,\"okand_nyckel\":1}}"
check "save_profile utan CSRF-token"            "403" "${api_cookie[@]}" "${json[@]}" -d "$valid_profile" "$BASE/api/save_profile.php"
check "save_profile: GET"                       "405" "${api_cookie[@]}" "$BASE/api/save_profile.php"
big_body="{\"track\":\"$PROFILE_TRACK_URL\",\"settings\":{\"x\":\"$(head -c 70000 /dev/zero | tr '\0' 'a')\"}}"
check "save_profile: för stor kropp"            "413" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" --data-binary "$big_body" "$BASE/api/save_profile.php"
check "save_profile: ogiltig JSON"              "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d '{trasig' "$BASE/api/save_profile.php"
check "save_profile: okänt spår"                "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d '{"track":"music/finns_inte.mp3","settings":{"msc":0.5}}' "$BASE/api/save_profile.php"
check "save_profile: andra gruppens spår"       "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d "{\"track\":\"music/$(encode "$OTHER_GROUP_TRACK")\",\"settings\":{\"msc\":0.5}}" "$BASE/api/save_profile.php"
check "save_profile: volym 9"                   "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d "{\"track\":\"$PROFILE_TRACK_URL\",\"settings\":{\"msc\":9}}" "$BASE/api/save_profile.php"
check "save_profile: ogiltigt playMode"         "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d '{"track":"_settings","settings":{"playMode":"turbo"}}' "$BASE/api/save_profile.php"
check "save_profile: giltigt anrop"             "200" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d "$valid_profile" "$BASE/api/save_profile.php"
check "save_profile: giltiga _settings"         "200" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d "{\"track\":\"_settings\",\"settings\":{\"playMode\":\"shuffle\",\"playbackRate\":1.25,\"queue\":[\"$PROFILE_TRACK_URL\",\"music/finns_inte.mp3\"],\"queueCursor\":0}}" "$BASE/api/save_profile.php"
profiles=$(curl -s "${api_cookie[@]}" "$BASE/api/load_profiles.php")
if echo "$profiles" | grep -q '"msc":0.55' && echo "$profiles" | grep -q '"liked":true' && ! echo "$profiles" | grep -q 'okand_nyckel' \
   && echo "$profiles" | grep -q '"shuffle"' && ! echo "$profiles" | grep -q 'finns_inte'; then
    pass=$((pass + 1)); echo "  OK    sparad profil laddas; okänd nyckel och okänt köspår kastades"
else
    fail=$((fail + 1)); echo "  FEL   sparad profil saknas eller innehåller osanerad data: $profiles"
fi
check "save_playlist utan CSRF-token"           "403" "${api_cookie[@]}" "${json[@]}" -d '{"name":"x","tracks":[]}' "$BASE/api/save_playlist.php"
check "save_playlist: namn med bara kontrolltecken" "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d '{"name":"\u0001\u0002","tracks":[]}' "$BASE/api/save_playlist.php"
check "save_playlist: för långt namn"           "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d "{\"name\":\"$(head -c 150 /dev/zero | tr '\0' 'n')\",\"tracks\":[]}" "$BASE/api/save_playlist.php"
check "save_playlist: tracks är inte en lista"  "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d '{"name":"x","tracks":"nej"}' "$BASE/api/save_playlist.php"
check "save_playlist: giltigt anrop"            "200" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d "{\"name\":\"Smoke\",\"tracks\":[\"$PROFILE_TRACK_URL\",\"music/finns_inte.mp3\"]}" "$BASE/api/save_playlist.php"
playlists=$(curl -s "${api_cookie[@]}" "$BASE/api/load_playlists.php")
if echo "$playlists" | grep -q 'Smoke' && echo "$playlists" | grep -q '001_mediation_msc' && ! echo "$playlists" | grep -q 'finns_inte'; then
    pass=$((pass + 1)); echo "  OK    spellista sparad; okänt spår filtrerades bort"
else
    fail=$((fail + 1)); echo "  FEL   spellistan saknas eller innehåller okänt spår: $playlists"
fi
check "log_play utan CSRF-token"                "403" "${api_cookie[@]}" "${json[@]}" -d "{\"track\":\"$PROFILE_TRACK_URL\"}" "$BASE/api/log_play.php"
check "log_play: okänt spår"                    "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d '{"track":"music/finns_inte.mp3"}' "$BASE/api/log_play.php"
check "log_play: spår i annan grupp"            "400" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d "{\"track\":\"music/$(encode "$OTHER_GROUP_TRACK")\"}" "$BASE/api/log_play.php"
check "log_play: för stor kropp"                "413" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d "{\"track\":\"$(head -c 2000 /dev/zero | tr '\0' 'a')\"}" "$BASE/api/log_play.php"
check "log_play: giltigt anrop"                 "200" "${api_cookie[@]}" "${csrf[@]}" "${json[@]}" -d "{\"track\":\"$PROFILE_TRACK_URL\"}" "$BASE/api/log_play.php"
if sudo grep -q '"user":"__smoketest__"' /var/www/clio_music/data/plays.jsonl; then
    pass=$((pass + 1)); echo "  OK    spelningen loggades med användare, spår och tid"
else
    fail=$((fail + 1)); echo "  FEL   ingen loggrad för __smoketest__ i plays.jsonl"
fi

echo "== S3: gäster"
guest_jar=$(mktemp)
guest_token=$(curl -s -c "$guest_jar" -b "$guest_jar" "$BASE/" | page_token)
guest_csrf=(-H "X-CSRF-Token: $guest_token")
check "gäst: load_profiles ger tomt svar"       "200" -b "$guest_jar" "$BASE/api/load_profiles.php"
check "gäst: save_profile kräver inloggning"    "401" -b "$guest_jar" "${guest_csrf[@]}" "${json[@]}" -d "{\"track\":\"$GUEST_TRACK_URL\",\"settings\":{}}" "$BASE/api/save_profile.php"
check "gäst: save_playlist kräver inloggning"   "401" -b "$guest_jar" "${guest_csrf[@]}" "${json[@]}" -d '{"name":"x","tracks":[]}' "$BASE/api/save_playlist.php"
check "gäst: log_play utan CSRF-token"          "403" -b "$guest_jar" "${json[@]}" -d '{"track":"music/x.mp3"}' "$BASE/api/log_play.php"
# Okända spår skriver ingenting, men räknas mot gränsen: spam stoppas utan att loggen fylls.
for attempt in $(seq 1 10); do
    curl -s -o /dev/null -b "$guest_jar" "${guest_csrf[@]}" "${json[@]}" -d '{"track":"music/finns_inte.mp3"}' "$BASE/api/log_play.php"
done
check "gäst: 11:e log_play inom en minut"       "429" -b "$guest_jar" "${guest_csrf[@]}" "${json[@]}" -d '{"track":"music/finns_inte.mp3"}' "$BASE/api/log_play.php"
check_header "429 har Retry-After"               '^retry-after: [0-9]+' -b "$guest_jar" "${guest_csrf[@]}" "${json[@]}" -d '{"track":"music/finns_inte.mp3"}' "$BASE/api/log_play.php"
rm -f "$guest_jar"

echo "== S5: säkerhetsrubriker och nginx-gränser (T7)"
header_urls=("$BASE/" "$BASE/login.php" "$BASE/api/load_profiles.php" "$(music "$GUEST_TRACK")" "$BASE/finns_inte.txt" "$BASE/admin/")
for url in "${header_urls[@]}"; do
    short="${url#"$BASE"}"; short="${short:0:40}"
    check_header "nosniff: $short"                 '^x-content-type-options: nosniff'  "$url"
    check_header "X-Frame-Options: $short"         '^x-frame-options: deny'            "$url"
    check_header "Referrer-Policy: $short"         '^referrer-policy: strict-origin-when-cross-origin' "$url"
    check_header "Permissions-Policy: $short"      '^permissions-policy: .*camera=\(\)' "$url"
    check_header "CSP med frame-ancestors: $short" "^content-security-policy(-report-only)?: .*frame-ancestors 'none'" "$url"
done
check_header "media 206 har nosniff"                '^x-content-type-options: nosniff' -r 0-99 "$(music "$GUEST_TRACK")"
check_header "media 206 har CSP"                    '^content-security-policy' -r 0-99 "$(music "$GUEST_TRACK")"
check_header "Server-rubriken saknar versionsnummer" '^server: nginx[[:space:]]*$' "$BASE/login.php"
if curl -s -o /dev/null -D - "$BASE/login.php" | grep -qi '^x-powered-by'; then
    fail=$((fail + 1)); echo "  FEL   X-Powered-By läcker PHP-version"
else
    pass=$((pass + 1)); echo "  OK    ingen X-Powered-By"
fi
# nginx ska avvisa för stora kroppar innan PHP ser dem: 64k för /api/, 256k i övrigt.
# Kroppen läses från fil: ett enskilt kommandoradsargument får vara högst 128 kB i Linux.
big_body=$(mktemp)
head -c 70000 /dev/zero | tr '\0' 'a' > "$big_body"
check "api: 70 kB-kropp avvisas av nginx"           "413" -X POST -H 'Content-Type: application/json' --data-binary "@$big_body" "$BASE/api/log_play.php"
head -c 300000 /dev/zero | tr '\0' 'a' > "$big_body"
check "login: 300 kB-kropp avvisas av nginx"        "413" -X POST --data-binary "@$big_body" "$BASE/login.php"
rm -f "$big_body"
if curl -s "$BASE/" | grep -oiE '<script[^>]*>' | grep -qviE 'src=|application/json' || curl -s "$BASE/" | grep -qiE '\son(click|change|load|error)='; then
    fail=$((fail + 1)); echo "  FEL   index.php innehåller inline-skript eller on*-attribut"
else
    pass=$((pass + 1)); echo "  OK    index.php har inga inline-skript (CSP)"
fi

# Städa bort testets spår: räknarfiler och testets rader i auditloggen.
for key in "user:$bf_user" "ip:127.0.0.1"; do
    sudo rm -f "/var/www/clio_music/data/login_attempts/$(printf '%s' "$key" | sha256sum | cut -c1-64).json"
done
sudo php -r '
    [$file, $since] = [$argv[1], (int)$argv[2]];
    if (!is_file($file)) exit;
    $handle = fopen($file, "r+"); flock($handle, LOCK_EX);
    $kept = array_filter(explode("\n", stream_get_contents($handle)), function ($line) use ($since) {
        $entry = json_decode($line, true);
        if (!$entry) return $line !== "";
        $is_test = ($entry["ts"] ?? 0) >= $since
            && (($entry["ip"] ?? "") === "127.0.0.1" || str_contains($line, "__smoketest"));
        return !$is_test;
    });
    ftruncate($handle, 0); rewind($handle);
    fwrite($handle, $kept ? implode("\n", $kept) . "\n" : "");
    flock($handle, LOCK_UN); fclose($handle);
' /var/www/clio_music/data/audit.jsonl "$test_start"
rm -f "$jar"
# S3: städa bort testets profil, spellista, loggrader och hastighetsräknare.
sudo rm -f /var/www/clio_music/data/profiles/__smoketest__.json /var/www/clio_music/data/playlists/__smoketest__.json
for key in "log_play_guest:127.0.0.1" "log_play_user:__smoketest__"; do
    sudo rm -f "/var/www/clio_music/data/rate_limits/$(printf '%s' "$key" | sha256sum | cut -c1-64).json"
done
# plays.jsonl skrivs om på plats under flock (ingen rename: PHP håller LOCK_EX på samma inod).
sudo php -r '
    $file = $argv[1];
    if (!is_file($file)) exit;
    $handle = fopen($file, "r+"); flock($handle, LOCK_EX);
    $kept = array_filter(explode("\n", stream_get_contents($handle)), fn($line) => $line !== "" && !str_contains($line, "\"user\":\"__smoketest__\""));
    ftruncate($handle, 0); rewind($handle);
    fwrite($handle, $kept ? implode("\n", $kept) . "\n" : "");
    flock($handle, LOCK_UN); fclose($handle);
' /var/www/clio_music/data/plays.jsonl

echo "== S7: fynd från slutgranskningen"
check "tests/*.php körs inte via webben"       "403" "$BASE/tests/groups_store_test.php"
check "tests/api_validation_test.php"          "403" "$BASE/tests/api_validation_test.php"
check "api/_bootstrap.php direkt"              "403" "$BASE/api/_bootstrap.php"
check "api/_validation.php direkt"             "403" "$BASE/api/_validation.php"
check "admin/groups_store.php direkt"          "403" "$BASE/admin/groups_store.php"
check "data/ spärrad även för .php"            "403" "$BASE/data/x.php"
s7_admin=$(make_session "" 1)
session_files+=("$SESSION_DIR/sess_$s7_admin")
injected=$(curl -s -b "$COOKIE_NAME=$s7_admin" "$BASE/admin/?view=%22%3E%3Cmeta%20http-equiv%3Drefresh%3E")
if [[ "$injected" == *'<meta http-equiv=refresh>'* ]]; then
    fail=$((fail + 1)); echo "  FEL   admin ?view= ekas oescapat (HTML-injektion)"
else
    pass=$((pass + 1)); echo "  OK    admin ?view= kan inte injicera HTML"
fi

echo
echo "Resultat: $pass OK, $fail FEL"
[[ $fail -eq 0 ]]
