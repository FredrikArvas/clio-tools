"""
Engångsskript: skapar sekretesspolicy som publik webbsida i Odoo.
URL: /privacy

Kör: python create_privacy_page.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clio_odoo import connect

PAGE_URL = "/privacy"
PAGE_NAME = "Sekretesspolicy"

ARCH = """<t t-name="website.page_privacy" name="Sekretesspolicy">
  <t t-call="website.layout">
    <t t-set="pageName" t-value="'Sekretesspolicy'"/>
    <div id="wrap" class="oe_structure">
      <section class="s_text_block pt64 pb64">
        <div class="container">
          <div class="row">
            <div class="col-lg-8 offset-lg-2">
              <h1>Sekretesspolicy</h1>
              <p><strong>Applikation:</strong> Clio-agent-obit<br/>
              <strong>Ansvarig:</strong> Arvas International AB, Muskö<br/>
              <strong>Kontakt:</strong> <a href="mailto:fredrik@arvas.se">fredrik@arvas.se</a><br/>
              <strong>Senast uppdaterad:</strong> 2026-04-26</p>

              <h2>1. Vad vi gör</h2>
              <p>Clio-agent-obit är ett internt verktyg som bevakar svenska dödsannonser och
              jämför dem mot en personlig bevakningslista. Applikationen ansluter till Geni.com
              för att hämta familjerelationer och berika bevakade personers profiler.</p>

              <h2>2. Vilka uppgifter vi hämtar från Geni</h2>
              <ul>
                <li>Namn, födelsedata och dödsdata för bevakade personer och deras närmaste familj</li>
                <li>Familjerelationer (partner, barn, syskon, föräldrar)</li>
              </ul>
              <p>Vi hämtar enbart data för personer som redan finns i vår interna bevakningslista.
              Vi scrapar eller lagrar inte data i stor skala.</p>

              <h2>3. Hur uppgifterna används</h2>
              <p>Uppgifterna används uteslutande för att matcha dödsannonser mot bevakningslistan
              och skicka interna notifieringar till systemets ägare. Ingen data delas med tredje part.</p>

              <h2>4. Lagring</h2>
              <p>Hämtad Geni-data lagras inte permanent. Matchningsresultat sparas lokalt i en
              intern databas tillgänglig enbart för systemägaren.</p>

              <h2>5. Dina rättigheter</h2>
              <p>Om du finns i vår bevakningslista och vill bli borttagen, eller vill veta vilka
              uppgifter vi har om dig, kontakta oss på
              <a href="mailto:fredrik@arvas.se">fredrik@arvas.se</a>.</p>

              <h2>6. Ändringar</h2>
              <p>Vi kan uppdatera denna policy vid behov. Den senaste versionen finns alltid
              på denna sida.</p>

              <hr/>
              <p class="text-muted small">Arvas International AB &amp;bull; Muskö</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  </t>
</t>"""


def main():
    print("Ansluter till Odoo...")
    env = connect()

    WebsitePage = env["website.page"]
    IrUiView = env["ir.ui.view"]

    # Kolla om sidan redan finns
    existing = WebsitePage.search_read([("url", "=", PAGE_URL)], ["id", "name"])
    if existing:
        print(f"Sidan finns redan (id={existing[0]['id']}). Inget gjort.")
        print(f"URL: https://odoo.arvas.international{PAGE_URL}")
        return

    # Skapa view — extrahera heltal-ID ur recordset
    view_rec = IrUiView.create({
        "name": PAGE_NAME,
        "type": "qweb",
        "arch": ARCH,
    })
    view_id = view_rec.id if hasattr(view_rec, "id") else int(view_rec)
    print(f"View skapad: id={view_id}")

    # Skapa webbsida kopplad till view
    page_rec = WebsitePage.create({
        "name": PAGE_NAME,
        "url": PAGE_URL,
        "view_id": view_id,
        "is_published": True,
        "website_published": True,
    })
    page_id = page_rec.id if hasattr(page_rec, "id") else int(page_rec)
    print(f"Sida skapad: id={page_id}")
    print(f"Publik URL: https://odoo.arvas.international{PAGE_URL}")


if __name__ == "__main__":
    main()
