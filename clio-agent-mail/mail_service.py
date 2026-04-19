"""
mail_service.py — HTTP-relä för smtp_client

Kör på laptopen (port 7100) så att servern kan skicka mail
via POST /send trots att SMTP-portarna är blockerade från servern.

Kör: python mail_service.py [--port 7100]
Som tjänst: se clio-mail.service

Miljövariabler (clio-agent-mail/.env):
  IMAP_PASSWORD_CLIO      — Lösenord för clio@arvas.international
  CLIO_MAIL_SERVICE_PORT  — Port (default 7100)

Request: POST /send  { "to", "subject", "body", "html" }
"""

import argparse
import configparser
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dotenv import load_dotenv

# Windows/Python 3.14: tvinga IPv4 DNS (misslyckas annars med IPv6 link-local)
import sys as _sys, socket as _socket
if _sys.platform == "win32":
    _orig_gai = _socket.getaddrinfo
    def _ipv4_gai(host, port, family=0, type=0, proto=0, flags=0):
        if family == 0:
            family = _socket.AF_INET
        return _orig_gai(host, port, family, type, proto, flags)
    _socket.getaddrinfo = _ipv4_gai

BASE_DIR = Path(__file__).parent
ROOT_DIR = BASE_DIR.parent

load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env", override=True)

sys.path.insert(0, str(BASE_DIR))
import smtp_client

logger = logging.getLogger(__name__)


def _load_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(BASE_DIR / "clio.config")
    imap_pass = os.getenv("IMAP_PASSWORD_CLIO", "")
    if not imap_pass:
        raise EnvironmentError("IMAP_PASSWORD_CLIO saknas i .env")
    config.set("mail", "imap_password_clio", imap_pass)
    return config


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/send":
            self._respond(404, {"ok": False, "error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._respond(400, {"ok": False, "error": "bad JSON"})
            return

        if not {"to", "subject", "body"}.issubset(data):
            self._respond(400, {"ok": False, "error": "saknade fält: to/subject/body"})
            return

        try:
            smtp_client.send_email(
                config=_load_config(),
                from_account_key="clio",
                to_addr=data["to"],
                subject=data["subject"],
                body=data["body"],
                html_body=data.get("html"),
            )
            self._respond(200, {"ok": True})
        except Exception as e:
            logger.error(f"send_email-fel: {e}")
            self._respond(500, {"ok": False, "error": str(e)})

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"ok": True, "service": "clio-mail"})
        else:
            self._respond(404, {"ok": False})

    def _respond(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.info(fmt % args)


def run(port: int):
    server = HTTPServer(("0.0.0.0", port), _Handler)
    logger.info(f"clio-mail-service lyssnar på 0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stänger clio-mail-service")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="clio-mail HTTP-relä")
    parser.add_argument(
        "--port", type=int,
        default=int(os.getenv("CLIO_MAIL_SERVICE_PORT", "7100")),
    )
    run(parser.parse_args().port)


if __name__ == "__main__":
    main()
