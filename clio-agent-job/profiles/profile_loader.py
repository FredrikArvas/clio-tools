"""
profile_loader.py
Läser en kandidatprofil och returnerar en dict.

Stödjer två källor:
  1. YAML-fil  — default, all befintlig funktionalitet oförändrad
  2. Odoo      — om YAML-stubben innehåller "source: odoo" hämtas profilen
                  från clio.job.profile i Odoo via email-match på res.partner

Odoo-stub (tunn YAML):
    source: odoo
    email: richard.anderberg@live.com
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

_DEFAULT_PROFILE = Path(__file__).parent / "richard.yaml"


# ---------------------------------------------------------------------------
# Publik API
# ---------------------------------------------------------------------------

def load_profile(path: Optional[Path] = None) -> dict:
    """
    Läser profil och returnerar en dict.
    Kastar ValueError om profilen saknas eller är ogiltig.
    Kastar ImportError om PyYAML saknas (YAML-läge).
    """
    if not _HAS_YAML:
        raise ImportError("PyYAML saknas — kör: pip install pyyaml")

    profile_path = path or _DEFAULT_PROFILE

    if not profile_path.exists():
        raise ValueError(f"Profilfil hittades inte: {profile_path}")

    with open(profile_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"Ogiltig profilfil (förväntade YAML-dict): {profile_path}")

    # --- Odoo-delegering ---
    if data.get("source") == "odoo":
        email = data.get("email", "").strip()
        if not email:
            raise ValueError(
                f"source: odoo kräver fältet 'email' i {profile_path}"
            )
        return _load_profile_from_odoo(email)

    # --- YAML-profil (befintligt beteende) ---
    if data.get("profile_type") == "recruiter":
        required = ["name", "target_candidate"]
    else:
        required = ["name", "role", "target_roles"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Profil saknar obligatoriska fält: {missing}")

    return data


def profile_summary(profile: dict) -> str:
    """Kortfattad textsammanfattning av profilen för loggning."""
    name = profile.get("name", "okänd")
    role = profile.get("role", "")
    geo  = profile.get("geography", "")
    src  = " [odoo]" if profile.get("_source") == "odoo" else ""
    return f"{name} — {role} ({geo}){src}"


# ---------------------------------------------------------------------------
# Privat: Odoo-laddare
# ---------------------------------------------------------------------------

def _split_lines(text) -> list[str]:
    """Delar upp ett textblock (en post per rad) till en lista."""
    if not text:
        return []
    return [line.strip() for line in str(text).splitlines() if line.strip()]


def _load_profile_from_odoo(email: str) -> dict:
    """
    Hämtar kandidatprofil från Odoo via email-match på res.partner.
    Kräver ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD i miljön (.env).
    Kastar ValueError om ingen aktiv profil hittas.
    """
    try:
        from clio_odoo import connect
    except ImportError as exc:
        raise ImportError(
            "clio_odoo saknas — se clio-tools/clio_odoo/"
        ) from exc

    env = connect()
    Partner = env["res.partner"]

    partners = Partner.search_read(
        [("email", "=", email), ("clio_job_watch", "=", True)],
        ["id", "name", "lang", "clio_job_profile_ids"],
    )
    if not partners:
        raise ValueError(
            f"Ingen aktiv clio_job-profil i Odoo för e-post: {email}\n"
            "Kontrollera att res.partner har clio_job_watch=True och att "
            "e-postadressen matchar exakt."
        )

    partner = partners[0]
    profile_ids = partner.get("clio_job_profile_ids") or []
    if not profile_ids:
        raise ValueError(
            f"Partner {partner['name']} ({email}) har clio_job_watch=True "
            "men saknar en kopplad clio.job.profile-post."
        )

    # Språk: "sv_SE" → "sv"
    raw_lang = partner.get("lang") or "sv_SE"
    language = raw_lang.split("_")[0]

    Profile = env["clio.job.profile"]
    rows = Profile.search_read(
        [("id", "=", profile_ids[0])],
        [
            "report_email", "role", "seniority", "geography", "hybrid_ok",
            "background", "education", "target_roles", "signal_keywords",
        ],
    )
    if not rows:
        raise ValueError(
            f"clio.job.profile (id={profile_ids[0]}) hittades inte i Odoo."
        )

    row = rows[0]
    return {
        "name":            partner["name"],
        "email":           (row.get("report_email") or "").strip() or email,
        "language":        language,
        "role":            row.get("role") or "",
        "seniority":       row.get("seniority") or "",
        "geography":       row.get("geography") or "",
        "hybrid_ok":       bool(row.get("hybrid_ok")),
        "background":      _split_lines(row.get("background")),
        "education":       _split_lines(row.get("education")),
        "target_roles":    _split_lines(row.get("target_roles")),
        "signal_keywords": _split_lines(row.get("signal_keywords")),
        # Intern markering — visas i profile_summary(), inte i mail
        "_source":         "odoo",
    }
