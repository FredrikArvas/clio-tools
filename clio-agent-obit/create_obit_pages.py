"""
Engångsskript: skapar Obit-huvudsida + undersidor för terms och privacy i Odoo.

Kör: python create_obit_pages.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clio_odoo import connect

PAGES = [
    {
        "url": "/obit",
        "name": "Obit — Dödsannonsbevakning",
        "t_name": "website.page_obit",
        "arch_body": """
              <h1>Obit — Dödsannonsbevakning</h1>
              <p class="lead">Clio Obit är ett automatiserat system som bevakar svenska
              dödsannonser och matchar dem mot en personlig bevakningslista.</p>

              <h2>Hur det fungerar</h2>
              <p>Varje morgon hämtar systemet nya dödsannonser från svenska källor
              (familjesidan.se, Fonus m.fl.) och jämför dem mot en lista med bevakade personer.
              Matchning sker på namn, födelsedata och familjerelationer.</p>
              <p>För att stärka matchningen hämtas familjeträdsdata från Geni.com via officiellt API —
              partner, barn, syskon och föräldrar används som ett "fingeravtryck" som jämförs
              mot informationen i dödsannonsen.</p>

              <h2>Notifiering</h2>
              <ul>
                <li><strong>Viktig:</strong> direktnotis via e-post vid träff</li>
                <li><strong>Normal / Bra att veta:</strong> samlas i daglig digest</li>
              </ul>

              <h2>Drift</h2>
              <p>Systemet körs automatiskt en gång per dag och kräver ingen manuell hantering.
              Alla träffar och körningar loggas internt.</p>

              <h2>Kontakt</h2>
              <p>Systemet ägs och drivs av Arvas International AB, Muskö.<br/>
              Frågor: <a href="mailto:fredrik@arvas.se">fredrik@arvas.se</a></p>

              <div class="mt-5">
                <a href="/obit/privacy" class="btn btn-outline-secondary btn-sm me-2">Sekretesspolicy</a>
                <a href="/obit/terms" class="btn btn-outline-secondary btn-sm">Användarvillkor</a>
              </div>
""",
    },
    {
        "url": "/obit/privacy",
        "name": "Obit — Sekretesspolicy",
        "t_name": "website.page_obit_privacy",
        "arch_body": """
              <h1>Sekretesspolicy</h1>
              <p><strong>Applikation:</strong> Clio Obit<br/>
              <strong>Ansvarig:</strong> Arvas International AB, Muskö<br/>
              <strong>Kontakt:</strong> <a href="mailto:fredrik@arvas.se">fredrik@arvas.se</a><br/>
              <strong>Senast uppdaterad:</strong> 2026-04-26</p>

              <h2>1. Vad vi gör</h2>
              <p>Clio Obit bevakar svenska dödsannonser och jämför dem mot en personlig
              bevakningslista. Systemet ansluter till Geni.com via officiellt API för att hämta
              familjerelationer som används vid matchning.</p>

              <h2>2. Vilka uppgifter vi hämtar från Geni</h2>
              <ul>
                <li>Namn, födelsedata och dödsdata för bevakade personer och deras närmaste familj</li>
                <li>Familjerelationer: partner, barn, syskon och föräldrar</li>
              </ul>
              <p>Vi hämtar enbart data för personer som finns i vår bevakningslista.
              Vi scrapar eller lagrar inte data i stor skala.</p>

              <h2>3. Hur uppgifterna används</h2>
              <p>Uppgifterna används uteslutande för intern matchning och notifiering.
              Ingen data delas med tredje part.</p>

              <h2>4. Lagring</h2>
              <p>Hämtad Geni-data lagras inte permanent. Matchningsresultat sparas i en intern
              databas tillgänglig enbart för systemägaren.</p>

              <h2>5. Dina rättigheter</h2>
              <p>Vill du bli borttagen från bevakningslistan eller veta vilka uppgifter vi har
              om dig? Kontakta oss på <a href="mailto:fredrik@arvas.se">fredrik@arvas.se</a>.</p>

              <h2>6. Ändringar</h2>
              <p>Den senaste versionen av denna policy finns alltid på denna sida.</p>

              <div class="mt-5">
                <a href="/obit" class="btn btn-outline-secondary btn-sm">← Tillbaka till Obit</a>
              </div>
""",
    },
    {
        "url": "/obit/terms",
        "name": "Obit — Användarvillkor",
        "t_name": "website.page_obit_terms",
        "arch_body": """
              <h1>Användarvillkor</h1>
              <p><strong>Applikation:</strong> Clio Obit<br/>
              <strong>Ansvarig:</strong> Arvas International AB, Muskö<br/>
              <strong>Kontakt:</strong> <a href="mailto:fredrik@arvas.se">fredrik@arvas.se</a><br/>
              <strong>Senast uppdaterad:</strong> 2026-04-26</p>

              <h2>1. Om applikationen</h2>
              <p>Clio Obit är ett internt verktyg ägt och drivet av Arvas International AB.
              Systemet ansluter till Geni.com via officiellt API för att hämta familjerelationer
              i syfte att matcha dödsannonser mot en personlig bevakningslista.</p>

              <h2>2. Tillåten användning</h2>
              <p>Systemet används uteslutande internt av Arvas International AB.
              Ingen allmän registrering eller extern åtkomst erbjuds.</p>

              <h2>3. Geni-data</h2>
              <p>Data från Geni.com hanteras i enlighet med
              <a href="https://www.geni.com/about/terms" target="_blank">Genis användarvillkor</a>.
              Vi hämtar enbart data för specifikt utpekade personer och lagrar den inte permanent.</p>

              <h2>4. Ansvarsbegränsning</h2>
              <p>Arvas International AB ansvarar inte för fel eller förseningar i matchningen.
              Systemet är ett stödverktyg och ersätter inte manuell uppföljning vid
              tidskritiska ärenden.</p>

              <h2>5. Kontakt</h2>
              <p>Frågor besvaras via <a href="mailto:fredrik@arvas.se">fredrik@arvas.se</a>.</p>

              <div class="mt-5">
                <a href="/obit" class="btn btn-outline-secondary btn-sm">← Tillbaka till Obit</a>
              </div>
""",
    },
]

ARCH_TEMPLATE = """<t t-name="{t_name}" name="{name}">
  <t t-call="website.layout">
    <t t-set="pageName" t-value="'{name}'"/>
    <div id="wrap" class="oe_structure">
      <section class="s_text_block pt64 pb64">
        <div class="container">
          <div class="row">
            <div class="col-lg-8 offset-lg-2">
{body}
            </div>
          </div>
        </div>
      </section>
    </div>
  </t>
</t>"""


def create_page(env, page: dict):
    WebsitePage = env["website.page"]
    IrUiView = env["ir.ui.view"]

    existing = WebsitePage.search_read([("url", "=", page["url"])], ["id", "name"])
    if existing:
        print(f"  Finns redan (id={existing[0]['id']}) — hoppar över.")
        return

    arch = ARCH_TEMPLATE.format(
        t_name=page["t_name"],
        name=page["name"],
        body=page["arch_body"],
    )

    view_rec = IrUiView.create({"name": page["name"], "type": "qweb", "arch": arch})
    view_id = view_rec.id if hasattr(view_rec, "id") else int(view_rec)

    page_rec = WebsitePage.create({
        "name": page["name"],
        "url": page["url"],
        "view_id": view_id,
        "is_published": True,
        "website_published": True,
    })
    page_id = page_rec.id if hasattr(page_rec, "id") else int(page_rec)
    print(f"  Skapad: id={page_id} -> https://odoo.arvas.international{page['url']}")


def main():
    print("Ansluter till Odoo...")
    env = connect()

    for page in PAGES:
        print(f"\n{page['url']}")
        create_page(env, page)

    print("\nKlart.")


if __name__ == "__main__":
    main()
