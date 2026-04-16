"""
onboarding.py
Bygger och skickar välkomstmail till ny clio-job-kandidat.
Skickas automatiskt vid första körningen för en profil.
"""

from __future__ import annotations

from pathlib import Path


def build_onboarding_mail(profile: dict) -> tuple[str, str, str]:
    """Returnerar (subject, body_text, body_html) för onboarding-mail."""
    name = profile.get("name", "")
    first_name = name.split()[0] if name else "Hej"
    role = profile.get("role", "")
    geography = profile.get("geography", "")
    keywords = profile.get("signal_keywords", [])
    kw_str = ", ".join(keywords[:8]) + ("..." if len(keywords) > 8 else "")

    subject = f"[clio-job] Välkommen, {first_name} — signalbevakning aktiverad"

    # ── Plaintext ─────────────────────────────────────────────────────────────
    body_text = f"""\
Hej {first_name},

Du är nu registrerad i clio-job. Tjänsten bevakar marknadssignaler
varje morgon och hör av sig när något relevant dyker upp för just dig.

HUR DET FUNGERAR
{"─" * 54}
Varje dag läser vi igenom hundratals artiklar från Di, Dagens
Samhälle, Computer Sweden, MFN, SAP News och fler källor. Vi letar
efter signaler — ny ledning, förvärv, digitaliseringsprogram,
omorganisationer, investeringar — saker som brukar leda till att
roller öppnar sig INNAN jobbannonsen är skriven.

Du hör bara av oss när vi hittar något relevant.
Tystnad = inga signaler idag. Det är normalt.

DIN PROFIL
{"─" * 54}
Roll:      {role}
Ort:       {geography}

Vi bevakar bl.a.:
  {kw_str}

AVREGISTRERING ELLER JUSTERING
{"─" * 54}
Svara på detta mail om du vill:
  · Avregistrera dig — skriv "STOPP"
  · Lägga till eller ta bort bevakningsord
  · Ändra något i din profil

{"─" * 54}
Clio · clio@arvas.international
"""

    # ── HTML ──────────────────────────────────────────────────────────────────
    kw_tags = "".join(
        f'<span style="display:inline-block;background:#ecf0f1;border-radius:3px;'
        f'padding:2px 8px;margin:2px;font-size:12px;color:#555;">{kw}</span>'
        for kw in keywords[:10]
    )

    body_html = f"""<!DOCTYPE html>
<html lang="sv">
<head><meta charset="utf-8"><title>{subject}</title></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#2c3e50;">
  <div style="background:#2c3e50;padding:24px 20px;color:white;">
    <h2 style="margin:0;font-size:22px;">Välkommen till clio-job, {first_name}!</h2>
    <p style="margin:8px 0 0 0;opacity:0.75;font-size:13px;">Signalbevakning aktiverad</p>
  </div>
  <div style="padding:24px 20px;">

    <p style="font-size:15px;">Du är nu registrerad i clio-job. Vi bevakar marknadssignaler
    varje morgon och hör av oss när något relevant dyker upp för just dig.</p>

    <h3 style="color:#2c3e50;border-bottom:2px solid #ecf0f1;padding-bottom:8px;">
      Hur det fungerar</h3>
    <p>Varje dag läser vi igenom hundratals artiklar från Di, Dagens Samhälle,
    Computer Sweden, MFN, SAP News och fler källor. Vi letar efter signaler —
    ny ledning, förvärv, digitaliseringsprogram, omorganisationer, investeringar —
    saker som brukar leda till att roller öppnar sig <strong>innan</strong>
    jobbannonsen är skriven.</p>
    <p style="background:#f0f9f0;border-left:4px solid #27ae60;padding:10px 14px;
    border-radius:0 4px 4px 0;">
      Du hör bara av oss när vi hittar något relevant.
      <strong>Tystnad = inga signaler idag.</strong> Det är normalt.
    </p>

    <h3 style="color:#2c3e50;border-bottom:2px solid #ecf0f1;padding-bottom:8px;">
      Din profil</h3>
    <table style="width:100%;border-collapse:collapse;font-size:14px;">
      <tr><td style="padding:4px 0;color:#888;width:80px;">Roll</td>
          <td style="padding:4px 0;font-weight:bold;">{role}</td></tr>
      <tr><td style="padding:4px 0;color:#888;">Ort</td>
          <td style="padding:4px 0;">{geography}</td></tr>
    </table>
    <p style="margin:12px 0 6px 0;font-size:13px;color:#888;">Vi bevakar bl.a.:</p>
    <div>{kw_tags}</div>

    <h3 style="color:#2c3e50;border-bottom:2px solid #ecf0f1;padding-bottom:8px;
    margin-top:24px;">Avregistrering eller justering</h3>
    <p>Svara på detta mail om du vill:</p>
    <ul style="line-height:1.9;">
      <li>Avregistrera dig — skriv <strong>"STOPP"</strong></li>
      <li>Lägga till eller ta bort bevakningsord</li>
      <li>Ändra något i din profil</li>
    </ul>

  </div>
  <div style="background:#ecf0f1;padding:12px 20px;font-size:11px;
  color:#7f8c8d;text-align:center;">
    Clio &middot; clio@arvas.international
  </div>
</body>
</html>"""

    return subject, body_text, body_html
