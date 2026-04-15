"""
reporter.py
Bygger mailrapport (HTML + plaintext) från analysresultat.
Format enligt ADD avsnitt 10.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_BASE_DIR = Path(__file__).parent
_SOURCES_DIR = _BASE_DIR / "sources"
if str(_SOURCES_DIR) not in sys.path:
    sys.path.insert(0, str(_SOURCES_DIR))

from source_base import Article  # noqa: E402

_ACTION_LABELS = {
    "ansök_nu": "Ansök nu",
    "nätverka": "Nätverka",
    "bevaka":   "Bevaka",
    "avstå":    "Avstå",
}

_STRENGTH_LABELS = {
    "svag":  "Svag",
    "medel": "Medel",
    "stark": "Stark",
}


@dataclass
class MatchedArticle:
    article: Article
    result: object  # AnalysisResult — undviker cirkulär import


def build_report(
    matched: list,
    profile: dict,
    total_fetched: int,
    total_new: int,
) -> tuple:
    """Returnerar (subject, body_text, body_html)."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    name = profile.get("name", "kandidat")
    first_name = name.split()[0]
    count = len(matched)

    subject = f"[clio-job] Förändringssignaler — {today}"

    sorted_matches = sorted(matched, key=lambda m: m.result.match_score, reverse=True)

    # ── Plaintext ─────────────────────────────────────────────────────────────
    lines = [
        f"Hej {first_name},",
        "",
        f"Clio har läst {total_new} nya artiklar (totalt {total_fetched} hämtade).",
        f"{count} av dem innehåller relevanta signaler.",
        "",
        "── TOPP-FYND " + "─" * 40,
        "",
    ]

    for i, m in enumerate(sorted_matches[:5], 1):
        a = m.article
        r = m.result
        roles_str = ", ".join(r.potential_roles) if r.potential_roles else "—"
        action_str = _ACTION_LABELS.get(r.recommended_action, r.recommended_action)
        strength_str = _STRENGTH_LABELS.get(r.signal_strength, r.signal_strength)
        lines += [
            f"[{i}] {a.title}",
            f"    Källa: {a.source}  |  Datum: {a.published_str()}",
            f"    Signal: {r.signal_type} ({strength_str})",
            f"    Matchning: {r.match_score}/100",
            f"    Varför: {r.match_reason}",
            f"    Möjliga roller: {roles_str}",
            f"    Åtgärd: {action_str}",
            f"    Kontakttips: {r.contact_hint}",
            f"    Länk: {a.url}",
            "",
        ]

    top3 = sorted_matches[:3]
    lines += ["── NÄSTA STEG " + "─" * 39]
    for m in top3:
        action_str = _ACTION_LABELS.get(m.result.recommended_action, m.result.recommended_action)
        lines.append(f"  • {m.article.title[:60]}… → {action_str}")
    lines += ["", "─" * 54, "Clio · clio@arvas.international"]

    body_text = "\n".join(lines)

    # ── HTML ──────────────────────────────────────────────────────────────────
    html_items = []
    for i, m in enumerate(sorted_matches[:5], 1):
        a = m.article
        r = m.result
        roles_str = ", ".join(r.potential_roles) if r.potential_roles else "—"
        action_str = _ACTION_LABELS.get(r.recommended_action, r.recommended_action)
        strength_str = _STRENGTH_LABELS.get(r.signal_strength, r.signal_strength)
        score_color = "#c0392b" if r.match_score >= 75 else "#e67e22" if r.match_score >= 60 else "#27ae60"
        html_items.append(f"""
        <div style="border-left:4px solid {score_color};padding:12px 16px;margin:16px 0;background:#fafafa;">
          <p style="margin:0 0 6px 0;font-size:16px;font-weight:bold;">
            [{i}] <a href="{a.url}" style="color:#2c3e50;">{a.title}</a>
          </p>
          <p style="margin:2px 0;color:#555;font-size:13px;">
            <strong>Källa:</strong> {a.source} &nbsp;|&nbsp; <strong>Datum:</strong> {a.published_str()}
          </p>
          <p style="margin:2px 0;font-size:13px;">
            <strong>Signal:</strong> {r.signal_type} ({strength_str}) &nbsp;|&nbsp;
            <strong>Matchning:</strong> <span style="color:{score_color};font-weight:bold;">{r.match_score}/100</span>
          </p>
          <p style="margin:2px 0;font-size:13px;"><strong>Varför:</strong> {r.match_reason}</p>
          <p style="margin:2px 0;font-size:13px;"><strong>Möjliga roller:</strong> {roles_str}</p>
          <p style="margin:2px 0;font-size:13px;"><strong>Åtgärd:</strong> {action_str}</p>
          <p style="margin:2px 0;font-size:13px;"><strong>Kontakttips:</strong> {r.contact_hint}</p>
        </div>""")

    next_steps_html = ""
    for m in top3:
        action_str = _ACTION_LABELS.get(m.result.recommended_action, m.result.recommended_action)
        title_short = m.article.title[:60] + ("…" if len(m.article.title) > 60 else "")
        next_steps_html += f"<li>{title_short} → <strong>{action_str}</strong></li>"

    body_html = f"""<!DOCTYPE html>
<html lang="sv">
<head><meta charset="utf-8"><title>{subject}</title></head>
<body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;color:#2c3e50;">
  <div style="background:#2c3e50;padding:20px;color:white;">
    <h2 style="margin:0;font-size:20px;">Clio-job — Förändringssignaler</h2>
    <p style="margin:6px 0 0 0;opacity:0.8;font-size:13px;">{today}</p>
  </div>
  <div style="padding:20px;">
    <p>Hej {first_name},</p>
    <p>Clio har läst <strong>{total_new}</strong> nya artiklar sedan senaste rapporten.
       <strong>{count}</strong> av dem innehåller relevanta signaler.</p>
    <h3 style="border-bottom:2px solid #ecf0f1;padding-bottom:8px;">Topp-fynd</h3>
    {"".join(html_items)}
    <h3 style="border-bottom:2px solid #ecf0f1;padding-bottom:8px;">Nästa steg</h3>
    <ul style="line-height:1.8;">{next_steps_html}</ul>
  </div>
  <div style="background:#ecf0f1;padding:12px 20px;font-size:11px;color:#7f8c8d;text-align:center;">
    Clio &middot; clio@arvas.international
  </div>
</body>
</html>"""

    return subject, body_text, body_html
