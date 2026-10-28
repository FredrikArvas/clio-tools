"""
fetch.py — Gmail IMAP-bilage-hämtare

Hämtar PDF-bilagor (eller angivna format) från Gmail-konton
baserat på jobb-konfiguration i clio.config.

Stöder valfri Gmail-taggning: tag_fetched = true i jobbet sätter
en label (fetched_label) på varje mail vars bilagor sparats.
"""
import configparser
import email
import imaplib
import os
import re
import unicodedata
from dataclasses import dataclass, field
from email.header import decode_header
from pathlib import Path
from typing import List


@dataclass
class FetchResult:
    job: str
    saved: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    already_exists: List[str] = field(default_factory=list)
    tagged: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _decode_str(value, encoding=None) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode(encoding or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError):
            return value.decode("latin-1", errors="replace")
    return value or ""


def _decode_header_str(raw: str) -> str:
    parts = decode_header(raw or "")
    return "".join(_decode_str(part, enc) for part, enc in parts).strip()


def _password_for(account_key: str) -> str:
    env_key = f"GMAIL_APP_PASSWORD_{account_key.upper()}"
    pw = os.environ.get(env_key, "")
    return pw.replace(" ", "")


def _ensure_label(imap: imaplib.IMAP4_SSL, label: str) -> None:
    """Skapar Gmail-label om den inte redan finns."""
    try:
        imap.create(f'"{label}"')
    except imaplib.IMAP4.error:
        pass  # Finns redan


def _tag_message(imap: imaplib.IMAP4_SSL, msg_id: bytes, label: str,
                 verbose: bool, result: FetchResult) -> None:
    """Kopierar meddelandet till label-mappen (= taggar det i Gmail)."""
    try:
        status, _ = imap.copy(msg_id, f'"{label}"')
        if status == "OK":
            mid = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
            result.tagged.append(mid)
            if verbose:
                print(f"    [taggad] {label}")
        else:
            result.errors.append(f"Kunde inte tagga msg {msg_id}: {status}")
    except Exception as e:
        result.errors.append(f"Taggningsfel msg {msg_id}: {e}")


def _extract_body(msg) -> str:
    """Returnerar text/plain ur ett mail, annars text/html som fallback."""
    for content_type in ("text/plain", "text/html"):
        for part in msg.walk():
            if part.get_content_type() == content_type:
                payload = part.get_payload(decode=True)
                if payload:
                    return _decode_str(payload, part.get_content_charset())
    return ""


def run_job(cfg: configparser.ConfigParser, job_key: str,
            skip_existing: bool = True, verbose: bool = True) -> FetchResult:
    result = FetchResult(job=job_key)
    section = f"job_{job_key}"

    if not cfg.has_section(section):
        result.errors.append(f"Jobb saknas i config: [{section}]")
        return result

    account_key   = cfg.get(section, "account")
    from_filter   = cfg.get(section, "from")
    target_dir    = Path(cfg.get(section, "target_dir"))
    raw_exts      = cfg.get(section, "extensions", fallback=".pdf")
    extensions    = {e.strip().lower() for e in raw_exts.split(",")}
    since_date    = cfg.get(section, "since", fallback="")
    tag_fetched   = cfg.getboolean(section, "tag_fetched", fallback=False)
    fetched_label = cfg.get(section, "fetched_label", fallback="Clio-Fetched")
    save_body     = cfg.getboolean(section, "save_body", fallback=False)

    acc_section = f"account_{account_key}"
    email_addr  = cfg.get(acc_section, "email")
    imap_host   = cfg.get(acc_section, "imap_host", fallback="imap.gmail.com")
    imap_port   = cfg.getint(acc_section, "imap_port", fallback=993)
    password    = _password_for(account_key)

    if not password:
        result.errors.append(
            f"Saknar lösenord: sätt GMAIL_APP_PASSWORD_{account_key.upper()} i .env"
        )
        return result

    target_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"  Ansluter till {imap_host} som {email_addr}...")

    try:
        with imaplib.IMAP4_SSL(imap_host, imap_port) as imap:
            imap.login(email_addr, password)
            imap.select("INBOX")

            if tag_fetched:
                _ensure_label(imap, fetched_label)

            criteria = f'FROM "{from_filter}"'
            if since_date:
                from datetime import datetime
                d = datetime.strptime(since_date, "%Y-%m-%d")
                imap_date = d.strftime("%d-%b-%Y")
                criteria += f' SINCE {imap_date}'

            # Exkludera redan taggade om tag_fetched är aktivt
            if tag_fetched:
                criteria = f'({criteria} UNKEYWORD Clio-Fetched-Done)'

            status, data = imap.search(None, criteria)
            if status != "OK":
                result.errors.append("IMAP-sökning misslyckades")
                return result

            msg_ids = data[0].split()
            if verbose:
                print(f"  Hittade {len(msg_ids)} mail från {from_filter}")

            for msg_id in msg_ids:
                status, msg_data = imap.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                saved_this_msg = []

                # Extrahera numerprefixet från ämnesraden (t.ex. "15. " ur "15. Läkarintyg")
                subject_raw_for_prefix = msg.get("Subject", "")
                subject_for_prefix = unicodedata.normalize(
                    "NFC", _decode_header_str(subject_raw_for_prefix)
                ).strip()
                num_match = re.match(r'^(\d+)', subject_for_prefix)
                mail_prefix = f"{num_match.group(1)}. " if (save_body and num_match) else ""

                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    if part.get("Content-Disposition") is None:
                        continue

                    filename_raw = part.get_filename()
                    if not filename_raw:
                        continue

                    filename = re.sub(
                        r'[<>:"/\\|?*\x00-\x1f]', "_",
                        unicodedata.normalize("NFC", _decode_header_str(filename_raw))
                    ).strip()
                    if not any(filename.lower().endswith(ext) for ext in extensions):
                        result.skipped.append(filename)
                        continue

                    # Prefixera med mailnummer om save_body är aktivt
                    prefixed_filename = f"{mail_prefix}{filename}" if mail_prefix else filename
                    target_path = target_dir / prefixed_filename
                    if skip_existing and target_path.exists():
                        result.already_exists.append(prefixed_filename)
                        if verbose:
                            print(f"    [finns redan] {prefixed_filename}")
                        continue

                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

                    target_path.write_bytes(payload)
                    result.saved.append(prefixed_filename)
                    saved_this_msg.append(prefixed_filename)
                    if verbose:
                        print(f"    [sparad] {prefixed_filename}")

                if save_body:
                    subject_raw = msg.get("Subject", "utan-amne")
                    subject = unicodedata.normalize("NFC", _decode_header_str(subject_raw))
                    safe_subject = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", subject).strip()[:200]
                    body_path = target_dir / f"{safe_subject}.txt"
                    if skip_existing and body_path.exists():
                        result.already_exists.append(body_path.name)
                        if verbose:
                            print(f"    [body finns redan] {body_path.name}")
                    else:
                        body_text = _extract_body(msg)
                        if body_text:
                            body_path.write_text(body_text, encoding="utf-8")
                            result.saved.append(body_path.name)
                            saved_this_msg.append(body_path.name)
                            if verbose:
                                print(f"    [body sparad] {body_path.name}")

                # Tagga mailet om minst en bilaga sparades
                if tag_fetched and saved_this_msg:
                    _tag_message(imap, msg_id, fetched_label, verbose, result)

    except imaplib.IMAP4.error as e:
        result.errors.append(f"IMAP-fel: {e}")
    except Exception as e:
        result.errors.append(f"Oväntat fel: {e}")

    return result


def run_all_jobs(cfg: configparser.ConfigParser,
                 verbose: bool = True) -> List[FetchResult]:
    jobs = [j.strip() for j in cfg.get("gmail", "jobs", fallback="").split(",") if j.strip()]
    results = []
    for job_key in jobs:
        if verbose:
            desc = cfg.get(f"job_{job_key}", "desc", fallback=job_key)
            print(f"\n[{job_key}] {desc}")
        result = run_job(cfg, job_key, verbose=verbose)
        results.append(result)
    return results
