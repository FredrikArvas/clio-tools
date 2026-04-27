"""
clio_service.py — HTTP API för clio-tools admin-kommandon

Modulrouting:
  /health             → hälsostatus
  /agents/status      → status för alla clio-agenter
  /mail/...           → clio-agent-mail/commands.py
  /rag/query          → clio-rag (Qdrant + Claude)
  /library/search     → Arvas Familjebibliotek (Notion)

Kör:   python clio_service.py [--port 7200]
Port:  CLIO_SERVICE_PORT     (default 7200)
Admin: CLIO_SERVICE_ADMIN    (default: mail.notify_address i clio.config)

Response: { "ok": true, "text": "...", ... }
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
RAG_DIR  = ROOT_DIR / "clio-rag"

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



def _route_mail_waiting_decide(data: dict) -> dict:
    sender = data.get("sender", "").strip()
    action = data.get("action", "").strip().upper()
    if not sender:
        return {"ok": False, "error": "saknar fält: sender"}
    if not action:
        return {"ok": False, "error": "saknar fält: action (VITLISTA/SVARTLISTA/BEHÅLL)"}
    return _dispatch("waiting_decide", body_text=sender, subject=action)

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


def _route_mail_waiting_json(_data: dict) -> dict:
    import state as st
    with st.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, sender, subject, date_received, account FROM mail "
            "WHERE status = ? ORDER BY created_at",
            (st.STATUS_WAITING,),
        ).fetchall()
    return {"ok": True, "waiting": [dict(r) for r in rows]}


def _route_mail_interview_sessions(_data: dict) -> dict:
    import state as st
    with st.get_connection() as conn:
        rows = conn.execute(
            "SELECT thread_id, participant_email, account_key, status, "
            "created_at, updated_at FROM interview_sessions ORDER BY created_at DESC"
        ).fetchall()
    return {"ok": True, "sessions": [dict(r) for r in rows]}


def _route_mail_interview_thread(data: dict) -> dict:
    thread_id = data.get("thread_id", "").strip()
    if not thread_id:
        return {"ok": False, "error": "saknat fält: thread_id"}
    import state as st
    messages = st.get_thread_history(thread_id)
    return {"ok": True, "messages": messages}


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


def _route_mail_ncc_lista_json(_data: dict) -> dict:
    import notion_data as nd
    config = _get_config()
    raw = config.get("mail", "knowledge_notion_db_ids", fallback="")
    db_entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not db_entries:
        return {"ok": False, "error": "Ingen projektdatabas konfigurerad."}
    db_id = db_entries[0].split(":")[0].strip()
    index = nd.get_project_index_full(db_id)
    return {"ok": True, "projects": index}


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


# ── RAG ──────────────────────────────────────────────────────────────────────

def _route_rag_query(data: dict) -> dict:
    q = data.get("q", "").strip()
    if not q:
        return {"ok": False, "error": "saknat fält: q"}
    top     = int(data.get("top", 5))
    use_ncc = bool(data.get("ncc", False))

    if not RAG_DIR.exists():
        return {"ok": False, "error": f"clio-rag ej hittad: {RAG_DIR}"}

    sys.path.insert(0, str(RAG_DIR))
    try:
        import importlib
        rag_query  = importlib.import_module("query")
        rag_config = importlib.import_module("config")

        collection = rag_config.NCC_COLLECTION_NAME if use_ncc else rag_config.COLLECTION_NAME
        vector     = rag_query.embed_query(q)
        hits       = rag_query.search_qdrant(vector, top_k=top, collection=collection)
        context    = rag_query.format_context(hits, is_ncc=use_ncc)
        answer     = rag_query.ask_claude(q, context, is_ncc=use_ncc)

        sources = []
        for hit in hits:
            p = hit.payload
            src = {"title": p.get("title", "?"), "score": round(hit.score, 3)}
            if use_ncc:
                src["url"] = p.get("ext_notion_url", "")
            else:
                src["page_start"] = p.get("ext_page_start")
                src["page_end"]   = p.get("ext_page_end")
            sources.append(src)

        return {"ok": True, "text": answer, "sources": sources}
    except Exception as e:
        logger.error(f"RAG query failed: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        if str(RAG_DIR) in sys.path:
            sys.path.remove(str(RAG_DIR))


# ── Bibliotek ─────────────────────────────────────────────────────────────────

def _route_library_search(data: dict) -> dict:
    q = data.get("q", "").strip()
    if not q:
        return {"ok": False, "error": "saknat fält: q"}

    notion_token = os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN", "")
    if not notion_token:
        return {"ok": False, "error": "NOTION_API_KEY saknas i .env"}

    import urllib.request, urllib.error
    db_id = "94906f71ee0f4ff88c4b28e822f6e670"
    url   = f"https://api.notion.com/v1/databases/{db_id}/query"
    body  = json.dumps({
        "filter": {"or": [
            {"property": "Titel",      "title":     {"contains": q}},
            {"property": "Författare", "rich_text": {"contains": q}},
        ]},
        "page_size": 20,
    }).encode()

    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization":  f"Bearer {notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type":   "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"Notion API-fel: {e.reason}"}

    books = []
    for page in result.get("results", []):
        props = page.get("properties", {})
        def _text(prop_name):
            p = props.get(prop_name, {})
            items = p.get("title") or p.get("rich_text") or p.get("select") and [p["select"]] or []
            return "".join(t.get("plain_text", "") for t in items) if items else ""
        books.append({
            "titel":      _text("Titel"),
            "forfattare": _text("Författare"),
            "hyllplats":  _text("Hyllplats"),
            "sprak":      _text("Språk"),
            "format":     _text("Format"),
            "hus":        _text("Hus"),
        })

    if not books:
        text = f"Inga böcker hittades för '{q}'."
    else:
        lines = [f"Bibliotek — {len(books)} träff(ar) för '{q}'", "─" * 44]
        for b in books:
            autor = f" / {b['forfattare']}" if b["forfattare"] else ""
            hyll  = f"  [{b['hyllplats']}]" if b["hyllplats"] else ""
            lines.append(f"{b['titel']}{autor}{hyll}")
        text = "\n".join(lines)

    return {"ok": True, "text": text, "books": books}


# ── Agentstatus ───────────────────────────────────────────────────────────────

def _route_agents_status(_data: dict) -> dict:
    import subprocess
    agents = {}

    for svc, label in [("clio-mail", "clio-agent-mail"), ("clio-service", "clio-service")]:
        r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
        agents[svc.replace("-", "_")] = {
            "label":  label,
            "status": r.stdout.strip(),
            "active": r.stdout.strip() == "active",
        }

    # Qdrant / RAG
    if RAG_DIR.exists():
        sys.path.insert(0, str(RAG_DIR))
        try:
            import importlib
            rag_config  = importlib.import_module("config")
            client      = rag_config.get_qdrant_client()
            collections = {c.name for c in client.get_collections().collections}
            agents["rag"] = {
                "label":   "clio-rag (Qdrant)",
                "status":  "active",
                "active":  True,
                "books":   "clio_books" in collections,
                "ncc":     "clio_ncc"   in collections,
            }
        except Exception as e:
            agents["rag"] = {"label": "clio-rag", "status": "error", "active": False, "error": str(e)}
        finally:
            if str(RAG_DIR) in sys.path:
                sys.path.remove(str(RAG_DIR))
    else:
        agents["rag"] = {"label": "clio-rag", "status": "not_installed", "active": False}

    return {"ok": True, "agents": agents}


# ── Serverhälsa ──────────────────────────────────────────────────────────────

_updates_cache: dict = {"ts": 0.0, "list": []}
_UPDATES_TTL = 3600  # sekunder — apt körs max en gång per timme


def _get_pending_updates() -> list[str]:
    import time, subprocess
    now = time.time()
    if now - _updates_cache["ts"] > _UPDATES_TTL:
        try:
            subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=30)
            r = subprocess.run(
                ["apt", "list", "--upgradable"],
                capture_output=True, text=True, timeout=15,
            )
            pkgs = [
                line.split("/")[0]
                for line in r.stdout.splitlines()
                if "/" in line
            ]
            _updates_cache["list"] = pkgs
        except Exception:
            pass
        _updates_cache["ts"] = now
    return _updates_cache["list"]


def _route_server_health(_data: dict) -> dict:
    try:
        import psutil
    except ImportError:
        return {"ok": False, "error": "psutil saknas — kör: pip install psutil"}

    cpu   = psutil.cpu_percent(interval=0.3)
    ram   = psutil.virtual_memory()
    disk  = psutil.disk_usage("/")
    uptime_s = int(__import__("time").time() - psutil.boot_time())
    days, rem = divmod(uptime_s, 86400)
    hours, _  = divmod(rem, 3600)

    updates = _get_pending_updates()

    return {
        "ok":            True,
        "cpu_percent":   round(cpu, 1),
        "ram_used_gb":   round(ram.used   / 1024 ** 3, 1),
        "ram_total_gb":  round(ram.total  / 1024 ** 3, 1),
        "ram_percent":   round(ram.percent, 1),
        "disk_used_gb":  round(disk.used  / 1024 ** 3, 0),
        "disk_total_gb": round(disk.total / 1024 ** 3, 0),
        "disk_percent":  round(disk.percent, 1),
        "uptime_days":   days,
        "uptime_hours":  hours,
        "updates":       updates,
        "updates_count": len(updates),
    }


# ── Docker-hälsa ─────────────────────────────────────────────────────────────

def _route_health_docker(_data: dict) -> dict:
    import subprocess
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
            capture_output=True, text=True, timeout=10,
        )
        containers = []
        for line in r.stdout.strip().splitlines():
            parts = line.split("\t")
            name    = parts[0] if len(parts) > 0 else "?"
            status  = parts[1] if len(parts) > 1 else "?"
            image   = parts[2] if len(parts) > 2 else "?"
            containers.append({
                "name":    name,
                "status":  status,
                "image":   image,
                "running": status.startswith("Up"),
            })
        return {"ok": True, "containers": containers}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Router ────────────────────────────────────────────────────────────────────

_ROUTES: dict[tuple[str, str], callable] = {
    ("GET",  "/agents/status"):        _route_agents_status,
    ("POST", "/agents/status"):        _route_agents_status,
    ("POST", "/rag/query"):            _route_rag_query,
    ("POST", "/library/search"):       _route_library_search,
    ("GET",  "/health"):               _route_health,
    ("GET",  "/health/server"):        _route_server_health,
    ("POST", "/health/server"):        _route_server_health,
    ("GET",  "/health/docker"):        _route_health_docker,
    ("POST", "/health/docker"):        _route_health_docker,
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
    ("GET",  "/mail/waiting/json"):           _route_mail_waiting_json,
    ("POST", "/mail/waiting/json"):           _route_mail_waiting_json,
    ("POST", "/mail/waiting/decide"):         _route_mail_waiting_decide,
    ("GET",  "/mail/interview/sessions"):     _route_mail_interview_sessions,
    ("POST", "/mail/interview/sessions"):     _route_mail_interview_sessions,
    ("POST", "/mail/interview/thread"):       _route_mail_interview_thread,
    ("POST", "/mail/interview/start"):        _route_mail_interview_start,
    ("POST", "/mail/interview/stop"):         _route_mail_interview_stop,
    ("GET",  "/mail/ncc/lista"):        _route_mail_ncc_lista,
    ("POST", "/mail/ncc/lista"):       _route_mail_ncc_lista,
    ("GET",  "/mail/ncc/lista/json"):  _route_mail_ncc_lista_json,
    ("POST", "/mail/ncc/lista/json"):  _route_mail_ncc_lista_json,
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
