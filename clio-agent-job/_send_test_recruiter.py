"""Engångsskript — skickar syntetiskt testmail för rekryterarläget."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from notifier import send_report

BODY_TEXT = """\
Hej Fredrik,

Clio har läst 278 artiklar (13 nya sedan senaste körningen).
1 av dem innehåller en relevant rekryteringssignal.

\u2500\u2500 TOPP-FYND \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
[1] Kito Crosby valjer Salesforce \u2014 avslutar SAP-avtal
    Kalla: SAP News  |  Datum: 2026-04-16
    Signal: plattformsbyte (Stark)
    Matchning: 78/100
    Malforetag: Kito Crosby
    Varfor: Bolaget migrerar fran SAP till Salesforce CRM.
            Intern SAP-kompetens blir overflödig inom 6-12 manader.
    Berord personal: SAP MM/SD-konsulter, SAP Basis, 5-15 personer
    Tidslinje: Oppna for byte Q3 2026
    Rekommendation: Bevaka 3 manader
    Kontakttips: Na IT-chefen via LinkedIn \u2014 namn Salesforce-migrationen,
                 erbjud SAP-till-Salesforce transitionskompetens

\u2500\u2500 NASTA STEG \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  * Kito Crosby valjer Salesforce... \u2192 Bevaka 3 manader

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
Clio \u00b7 clio@arvas.international
[TESTMAIL \u2014 syntetiska data baserade pa verklig korning 2026-04-15]
"""

BODY_HTML = """<!DOCTYPE html>
<html lang="sv">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;color:#2c3e50;">
  <div style="background:#1a3a5c;padding:20px;color:white;">
    <h2 style="margin:0;font-size:20px;">Clio-recruiter &#8212; SAP Kandidatsignaler</h2>
    <p style="margin:6px 0 0 0;opacity:0.8;font-size:13px;">2026-04-16 &middot; CapFM SAP-rekrytering</p>
  </div>
  <div style="padding:20px;">
    <p>Hej Fredrik,</p>
    <p>Clio har l&auml;st <strong>278</strong> artiklar (13 nya). <strong>1</strong> inneh&aring;ller en relevant rekryteringssignal.</p>
    <h3 style="border-bottom:2px solid #ecf0f1;padding-bottom:8px;">Topp-fynd</h3>
    <div style="border-left:4px solid #c0392b;padding:12px 16px;margin:16px 0;background:#fafafa;">
      <p style="margin:0 0 6px 0;font-size:16px;font-weight:bold;">[1] Kito Crosby v&auml;ljer Salesforce &#8212; avslutar SAP-avtal</p>
      <p style="margin:2px 0;color:#555;font-size:13px;"><strong>K&auml;lla:</strong> SAP News &nbsp;|&nbsp; <strong>Datum:</strong> 2026-04-16</p>
      <p style="margin:2px 0;font-size:13px;"><strong>Signal:</strong> plattformsbyte (Stark) &nbsp;|&nbsp;
         <strong>Matchning:</strong> <span style="color:#c0392b;font-weight:bold;">78/100</span></p>
      <p style="margin:2px 0;font-size:13px;"><strong>M&aring;lf&ouml;retag:</strong> Kito Crosby</p>
      <p style="margin:2px 0;font-size:13px;"><strong>Varf&ouml;r:</strong> Bolaget migrerar fr&aring;n SAP till Salesforce CRM.
         Intern SAP-kompetens blir &ouml;verf l&ouml;dig inom 6&#8211;12 m&aring;nader.</p>
      <p style="margin:2px 0;font-size:13px;"><strong>Ber&ouml;rd personal:</strong> SAP MM/SD-konsulter, SAP Basis, 5&#8211;15 personer</p>
      <p style="margin:2px 0;font-size:13px;"><strong>Tidslinje:</strong> &Ouml;ppna f&ouml;r byte Q3 2026</p>
      <p style="margin:2px 0;font-size:13px;"><strong>Rekommendation:</strong> Bevaka 3 m&aring;nader</p>
      <p style="margin:2px 0;font-size:13px;"><strong>Kontakttips:</strong> N&aring; IT-chefen via LinkedIn &#8212;
         n&auml;mn Salesforce-migrationen, erbjud SAP-till-Salesforce transitionskompetens</p>
    </div>
    <p style="font-size:11px;color:#999;">[TESTMAIL &#8212; syntetiska data baserade p&aring; verklig k&ouml;rning 2026-04-15]</p>
  </div>
  <div style="background:#ecf0f1;padding:12px 20px;font-size:11px;color:#7f8c8d;text-align:center;">
    Clio &middot; clio@arvas.international &middot; CapFM konfidentiellt
  </div>
</body>
</html>"""

send_report(
    subject="[clio-recruiter] SAP Kandidatsignaler \u2014 2026-04-16 (TESTMAIL)",
    body_text=BODY_TEXT,
    body_html=BODY_HTML,
    to_addr="fredrik.arvas@capgemini.com",
    dry_run=False,
)
print("Testmail skickat!")
