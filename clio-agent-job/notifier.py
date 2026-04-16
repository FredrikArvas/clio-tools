"""
notifier.py
SMTP-avsändare för clio-agent-job.

Delar infrastruktur med clio-agent-mail:
  - Anropar clio-agent-mail/smtp_client.send_email()
  - Lösenord hämtas från clio-agent-mail/.env (IMAP_PASSWORD_CLIO)
  - Kopia sparas automatiskt i IMAP Skickat-mappen

Beroende: kräver att clio-agent-mail/ finns som syskonmapp i clio-tools/.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BASE_DIR  = Path(__file__).parent
_ROOT_DIR  = _BASE_DIR.parent
_MAIL_DIR  = _ROOT_DIR / "clio-agent-mail"

if not _MAIL_DIR.exists():
    raise ImportError(
        f"clio-agent-mail saknas på förväntad plats: {_MAIL_DIR}\n"
        "notifier.py kräver clio-agent-mail som syskonmodul i clio-tools/."
    )

if str(_MAIL_DIR) not in sys.path:
    sys.path.insert(0, str(_MAIL_DIR))

# Ladda clio-agent-mails .env så att IMAP_PASSWORD_CLIO finns i environ
# innan load_config() anropas (den injicerar lösenordet i config-objektet)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_MAIL_DIR / ".env", override=False)
except ImportError:
    pass

from main import load_config      # noqa: E402
import smtp_client                # noqa: E402


def send_report(
    subject: str,
    body_text: str,
    body_html: str,
    to_addr: str,
    dry_run: bool = False,
) -> bool:
    """
    Skickar mailrapport till kandidatens adress via clio-agent-mails SMTP-infrastruktur.
    dry_run=True: skriver ut rapporten men skickar inget.
    Returnerar True vid lyckat skick (eller dry_run).
    """
    config = load_config()

    smtp_client.send_email(
        config,
        from_account_key="clio",
        to_addr=to_addr,
        subject=subject,
        body=body_text,
        html_body=body_html,
        dry_run=dry_run,
    )

    return True
