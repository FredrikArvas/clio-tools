"""
clio_service.py — HTTP API för clio-agent-mail admin-kommandon

Exponerar commands.dispatch() som REST-endpoints. Konsumeras av
clio_mail_admin (Odoo-addon) och framtida klienter.

Modulrouting (utbyggbar):
  /mail/...           → clio-agent-mail/commands.py
  /rag/...            → (framtida)
  /crm/...            → (framtida)

Kör:   python clio_service.py [--port 7200]
Port:  CLIO_SERVICE_PORT     (default 7200)
Admin: CLIO_SERVICE_ADMIN    (default: mail.notify_address i clio.config)

Request:  POST /mail/<command>   Content-Type: application/json  { ...args }
Response: { "ok": true, "text": "...", "outbound": [...] }
"""

from __future__ import annotations

import argparse
import configparser
import json
import logging
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).parent
ROOT_DIR = BASE_DIR.parent

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env", override=True)

sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(ROOT_DIR))

from imap_client import MailItem
import commands as cmd_module

logger = logging.getLogger(__name__)

_config: configparser.ConfigParser | None = None


def _get_config() -> configparser.ConfigParser:
    global _config
    if _config is None:
        _config = configparser.ConfigParser()
        _config.read(BASE_DIR / "clio.config", encoding="utf-8")
        imap_pass = os.getenv("IMAP_PASSWORD_CLIO", "")
        if imap_pass:
            _config.set("mail", "imap_password_clio", imap_pass)
    return _config


def _admin_email() -> str:
    env = os.getenv("CLIO_SERVICE_ADMIN", "")
    if env:
        return env
    return _get_config().get("mail", "notify_address", fallback="fredrik@arvas.international")


def _synthetic_mail(body_text: str = "", subject: str = "clio-service") -> MailItem:
    return MailItem(
        message_id=f"<clio-service-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}@arvas.international>",
        account="clio",
        sender=_admin_email(),
        subject=subject,
        body=body_text,
        date_received=datetime.utcnow().isoformat(),
        raw_uid="0",
    )


def _dispatch(command: str, body_text: str = "", subject: str = "") -> dict:
    mail = _synthetic_mail(body_text=body_text, subject=subject or command)
    result = cmd_module.dispatch(command, mail, _get_config())
    return {
        "ok": True,
        "text": result.reply_body,
        "outbound": [
            {"to": m.to_addr, "subject": m.subject, "body": m.body}
            for m in result.outbound
        ],
    }


# ── Route-handlers ────────────────────────────────────────────────────────────

def _route_health(_data: dict) -> dict:
    return {"ok": True, "service": "clio-service"}


def _route_mail_list(_data: dict) -> dict:
    return _dispatch("list")


def _route_mail_waiting(_data: dict) -> dict:
    return _dispatch("waiting")


def _route_mail_status(_data: dict) -> dict:
    return _dispatch("status")


def _route_mail_whitelist(data: dict) -> dict:
    body = data.get("email", "").strip()
    return _dispatch("whitelist", body_text=body)


def _route_mail_blacklist(data: dict) -> dict:
    email = data.get("email", "").strip()
    if not email:
        return {"ok": False, "error": "saknat fält: email"}
    return _dispatch("blacklist", body_text=email)


def _route_mail_interview_start(data: dict) -> dict:
    to      = data.get("to", "").strip()
    subject = data.get("subject", "Intervju").strip()
    context = data.get("context", "").strip()
    if not to:
        return {"ok": False, "error": "saknat fält: to"}
    lines = [f"till: {to}", f"ämne: {subject}"]
    if context:
        lines.append(context)
    return _dispatch("interview_start", body_text="\n".join(lines))


def _route_mail_interview_stop(data: dict) -> dict:
    participant = data.get("participant", "").strip()
    if not participant:
        return {"ok": False, "error": "saknat fält: participant"}
    return _dispatch("interview_stop", body_text=participant)


def _route_mail_ncc_lista(_data: dict) -> dict:
    return _dispatch("ncc_lista")


def _route_mail_ncc_ny(data: dict) -> dict:
    lines = []
    for field, key in [
        ("Kodord", "kodord"), ("Namn", "namn"), ("Sfär", "sfar"),
        ("Nr", "nr"), ("Förälder", "foralder"), ("Beskrivning", "beskrivning"),
    ]:
        val = data.get(key, "").strip()
        if val:
            lines.append(f"{field}: {val}")
    return _dispatch("ncc_ny", body_text="\n".join(lines))


def _route_mail_update(data: dict) -> dict:
    kodord  = data.get("kodord", "").strip()
    content = data.get("content", "").strip()
    if not kodord or not content:
        return {"ok": False, "error": "saknade fält: kodord, content"}
    subject = f"update #{kodord}"
    return _dispatch("update", body_text=content, subject=subject)


# ── Router ────────────────────────────────────────────────────────────────────

_ROUTES: dict[tuple[str, str], callable] = {
    ("GET",  "/health"):               _route_health,
    ("POST", "/health"):               _route_health,
    ("GET",  "/mail/list"):            _route_mail_list,
    ("POST", "/mail/list"):            _route_mail_list,
    ("GET",  "/mail/waiting"):         _route_mail_waiting,
    ("POST", "/mail/waiting"):         _route_mail_waiting,
    ("GET",  "/mail/status"):          _route_mail_status,
    ("POST", "/mail/status"):          _route_mail_status,
    ("GET",  "/mail/whitelist"):       _route_mail_whitelist,
    ("POST", "/mail/whitelist"):       _route_mail_whitelist,
    ("POST", "/mail/blacklist"):       _route_mail_blacklist,
    ("POST", "/mail/interview/start"): _route_mail_interview_start,
    ("POST", "/mail/interview/stop"):  _route_mail_interview_stop,
    ("GET",  "/mail/ncc/lista"):       _route_mail_ncc_lista,
    ("POST", "/mail/ncc/lista"):       _route_mail_ncc_lista,
    ("POST", "/mail/ncc/ny"):          _route_mail_ncc_ny,
    ("POST", "/mail/update"):          _route_mail_update,
}


class _Handler(BaseHTTPRequestHandler):
    def _handle(self, method: str):
        route_fn = _ROUTES.get((method, self.path))
        if not route_fn:
            self._respond(404, {"ok": False, "error": f"unknown route: {method} {self.path}"})
            return

        data: dict = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length", 0))
            if length:
                try:
                    data = json.loads(self.rfile.read(length))
                except json.JSONDecodeError:
                    self._respond(400, {"ok": False, "error": "bad JSON"})
                    return

        try:
            result = route_fn(data)
            self._respond(200, result)
        except Exception as e:
            logger.error(f"Route {method} {self.path} failed: {e}", exc_info=True)
            self._respond(500, {"ok": False, "error": str(e)})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _respond(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.info(fmt % args)


def run(port: int):
    server = HTTPServer(("0.0.0.0", port), _Handler)
    logger.info(f"clio-service lyssnar på 0.0.0.0:{port}  (admin: {_admin_email()})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stänger clio-service")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="clio HTTP service API")
    parser.add_argument(
        "--port", type=int,
        default=int(os.getenv("CLIO_SERVICE_PORT", "7200")),
    )
    run(parser.parse_args().port)


if __name__ == "__main__":
    main()
