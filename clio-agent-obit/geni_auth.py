"""
Engångsskript: OAuth2-autentisering mot Geni API.
Öppnar browser, fångar token via lokal callback-server, sparar i .env.

Kör: python geni_auth.py
Kräver: GENI_APP_ID och GENI_APP_SECRET i .env
"""
import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dotenv import load_dotenv, set_key

CALLBACK_PORT = 8765
CALLBACK_URL = f"http://localhost:{CALLBACK_PORT}/callback"
AUTH_URL = "https://www.geni.com/platform/oauth/authorize"
TOKEN_URL = "https://www.geni.com/platform/oauth/token"
ENV_FILE = Path(__file__).parent / ".env"


def main():
    load_dotenv(ENV_FILE)
    app_id = os.getenv("GENI_APP_ID")
    app_secret = os.getenv("GENI_APP_SECRET")

    if not app_id or not app_secret:
        print("Saknar GENI_APP_ID / GENI_APP_SECRET i .env")
        print("Registrera en app: https://www.geni.com/platform/developer/help")
        sys.exit(1)

    params = {
        "client_id": app_id,
        "redirect_uri": CALLBACK_URL,
        "response_type": "code",
        "display": "popup",
    }
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print(f"Oppnar browser for Geni-inloggning...")
    print(f"Auth-URL: {auth_url}")
    print(f"Callback-URL: {CALLBACK_URL}")
    webbrowser.open(auth_url)

    code_holder = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                code_holder["code"] = qs["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<h1>Klar! Du kan stanga webblesaren.</h1>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Ingen kod i callback.")

        def log_message(self, format, *args):
            pass  # tyst server

    print("Vantar pa callback pa port 8765...")
    server = HTTPServer(("localhost", CALLBACK_PORT), CallbackHandler)
    server.handle_request()

    if "code" not in code_holder:
        print("Ingen kod mottagen. Avbryt.")
        sys.exit(1)

    print(f"Kod mottagen, hamtar token...")
    import requests

    resp = requests.post(TOKEN_URL, data={
        "client_id": app_id,
        "client_secret": app_secret,
        "redirect_uri": CALLBACK_URL,
        "code": code_holder["code"],
        "grant_type": "authorization_code",
    }, timeout=15)

    if not resp.ok:
        print(f"Token-anrop misslyckades: {resp.status_code} {resp.text}")
        sys.exit(1)

    data = resp.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token", "")

    if not access_token:
        print(f"Ovant svar: {data}")
        sys.exit(1)

    set_key(str(ENV_FILE), "GENI_ACCESS_TOKEN", access_token)
    if refresh_token:
        set_key(str(ENV_FILE), "GENI_REFRESH_TOKEN", refresh_token)

    print(f"Token sparad i {ENV_FILE}")
    print("Kor nu: python geni_family.py <geni-URL>")


if __name__ == "__main__":
    main()
