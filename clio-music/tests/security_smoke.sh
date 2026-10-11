#!/usr/bin/env bash
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
PRIVATE_CHANNEL="001_mediation_vce.mp3"        # grupp RIM1, kanalfil (huvudfil _msc)
OTHER_GROUP_TRACK="Guldbodapolka 2026.mp3"     # grupp Guldbodalåtar
UNGROUPED_TRACK="demo_jatten_01.mp3"           # ingen grupp: inloggade ja, gäster nej
UNGROUPED_LYRICS="demo_jatten_01.lrc"
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
make_session() {
    local group="$1" id
    id="smoke$(openssl rand -hex 16)"
    php -r '
        $user = ["username" => "__smoketest__", "display" => "Smoketest", "admin" => 0, "groups" => [$argv[1]]];
        $now  = time();
        echo "cm_user|" . serialize($user) . "cm_created|" . serialize($now) . "cm_last_seen|" . serialize($now);
    ' "$group" | sudo tee "$SESSION_DIR/sess_$id" > /dev/null
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
check "gäst: spår utan grupp"                  "403" "$(music "$UNGROUPED_TRACK")"
check "gäst: lyrics till spår utan grupp (T3)" "403" "$(lyrics "$UNGROUPED_LYRICS")"
check_header "mp3: Content-Type audio/mpeg"         '^content-type: audio/mpeg' "$(music "$GUEST_TRACK")"
check_header "mp3: Cache-Control private, no-store" '^cache-control: private, no-store' "$(music "$GUEST_TRACK")"
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
check "inloggad: spår utan grupp"              "200" "${cookie[@]}" "$(music "$UNGROUPED_TRACK")"
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

echo
echo "Resultat: $pass OK, $fail FEL"
[[ $fail -eq 0 ]]
