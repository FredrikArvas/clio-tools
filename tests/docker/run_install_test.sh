#!/usr/bin/env bash
# run_install_test.sh — Kör clio-tools installationstest i Docker
#
# Användning:
#   bash tests/docker/run_install_test.sh            # normal körning
#   bash tests/docker/run_install_test.sh --keep     # behåll imagen för felsökning
#   bash tests/docker/run_install_test.sh --shell    # öppna shell inuti containern
#
# Förutsätter att Docker är installerat och kört.
# Körs från repo-roten (clio-tools/).

set -euo pipefail

IMAGE="clio-tools-test"
KEEP=false
OPEN_SHELL=false

for arg in "$@"; do
    case "$arg" in
        --keep)      KEEP=true ;;
        --shell)     OPEN_SHELL=true ;;
        --help|-h)
            echo "Användning: $0 [--keep] [--shell]"
            echo "  --keep    Behåll Docker-imagen efter test (för felsökning)"
            echo "  --shell   Öppna ett interaktivt shell inuti containern"
            exit 0 ;;
    esac
done

# ── Kontrollera att vi körs från repo-roten ───────────────────────────────────
if [[ ! -f "Dockerfile.test" ]]; then
    echo "ERROR: Kör skriptet från repo-roten (där Dockerfile.test finns)."
    exit 1
fi

# ── Kontrollera att Docker är tillgängligt ────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "ERROR: docker ej hittad i PATH."
    exit 1
fi

echo ""
echo "════════════════════════════════════════════════════"
echo "  clio-tools installationstest (Docker)"
echo "════════════════════════════════════════════════════"
echo ""

# ── Bygg imagen ───────────────────────────────────────────────────────────────
echo "▶ Bygger Docker-image: $IMAGE"
echo ""

if ! docker build -f Dockerfile.test -t "$IMAGE" .; then
    echo ""
    echo "❌ Byggfel — se output ovan."
    echo "   Tips: kör med --shell för att inspektera halvfärdig image:"
    echo "         docker run --rm -it python:3.12-slim bash"
    exit 1
fi

echo ""
echo "✅ Imagen byggd utan fel."
echo ""

# ── Öppna shell om --shell ────────────────────────────────────────────────────
if [[ "$OPEN_SHELL" == "true" ]]; then
    echo "▶ Öppnar shell i containern (exit för att avsluta)..."
    docker run --rm -it "$IMAGE" bash
    exit 0
fi

# ── Ta bort imagen om inte --keep ─────────────────────────────────────────────
cleanup() {
    if [[ "$KEEP" == "false" ]]; then
        echo ""
        echo "▶ Tar bort Docker-image: $IMAGE"
        docker rmi "$IMAGE" 2>/dev/null || true
    else
        echo ""
        echo "ℹ  Imagen behålls: $IMAGE"
        echo "   Kör: docker run --rm -it $IMAGE bash"
    fi
}
trap cleanup EXIT

echo "════════════════════════════════════════════════════"
echo "  Installationstest GODKÄNT ✅"
echo "  Python-paket installerade, QC grön, unit-tester OK."
echo "════════════════════════════════════════════════════"
echo ""
