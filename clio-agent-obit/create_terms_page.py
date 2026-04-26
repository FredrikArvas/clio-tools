"""
Engångsskript: skapar användarvillkor som publik webbsida i Odoo.
URL: /terms

Kör: python create_terms_page.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from clio_odoo import connect

PAGE_URL = "/terms"
PAGE_NAME = "Användarvillkor"

ARCH = """<t t-name="website.page_terms" name="Användarvillkor">
  <t t-call="website.layout">
    <t t-set="pageName" t-value="'Användarvillkor'"/>
    <div id="wrap" class="oe_structure">
      <section class="s_text_block pt64 pb64">
        <div class="container">
          <div class="row">
            <div class="col-lg-8 offset-lg-2">
              <h1>Användarvillkor</h1>
              <p><strong>Applikation:</strong> Clio-agent-obit<br/>
              <strong>Ansvarig:</strong> Arvas International AB, Muskö<br/>
              <strong>Kontakt:</strong> <a href="mailto:fredrik@arvas.se">fredrik@arvas.se</a><br/>
              <strong>Senast uppdaterad:</strong> 2026-04-26</p>

              <h2>1. Om applikationen</h2>
              <p>Clio-agent-obit är ett internt verktyg ägt och drivet av Arvas International AB.
              Applikationen ansluter till Geni.com via dess officiella API för att hämta
              familjerelationer i syfte att matcha dödsannonser mot en personlig bevakningslista.</p>

              <h2>2. Tillåten användning</h2>
              <p>Applikationen används uteslutande internt av Arvas International AB.
              Ingen allmän registrering eller extern åtkomst erbjuds.</p>

              <h2>3. Geni-data</h2>
              <p>Data som hämtas från Geni.com används i enlighet med
              <a href="https://www.geni.com/about/terms" target="_blank">Genis användarvillkor</a>.
              Vi hämtar enbart data för specifikt utpekade personer och lagrar den inte permanent.</p>

              <h2>4. Ansvarsbegränsning</h2>
              <p>Arvas International AB ansvarar inte för fel eller förseningar i dödsannonsmatchningen.
              Systemet är ett stödverktyg och ersätter inte manuell uppföljning vid tidskritiska ärenden.</p>

              <h2>5. Kontakt</h2>
              <p>Frågor om applikationen besvaras via
              <a href="mailto:fredrik@arvas.se">fredrik@arvas.se</a>.</p>

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

    existing = WebsitePage.search_read([("url", "=", PAGE_URL)], ["id", "name"])
    if existing:
        print(f"Sidan finns redan (id={existing[0]['id']}). Inget gjort.")
        print(f"URL: https://odoo.arvas.international{PAGE_URL}")
        return

    view_rec = IrUiView.create({
        "name": PAGE_NAME,
        "type": "qweb",
        "arch": ARCH,
    })
    view_id = view_rec.id if hasattr(view_rec, "id") else int(view_rec)
    print(f"View skapad: id={view_id}")

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
