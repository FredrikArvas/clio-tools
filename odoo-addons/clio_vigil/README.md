# clio_vigil — Odoo-addon

Odoo-vy för clio-vigil: prenumeranter, bevakningskällor, pipeline-kö och
färdiga bevakningsobjekt. Databas: `uap` (https://uap.arvas.international).

## Behörighetsgrupper

Tre nivåer under **Inställningar → Användare → Clio Vigil**:

| Grupp | Tänkt för |
|---|---|
| **Prenumerant** | Vänner/externa — ser och redigerar sitt eget abonnemang |
| **Användare** | Forskarkollegor — allt Prenumerant har + pipeline-läsrättigheter |
| *(Odoo-admin)* | Full kontroll inkl. Pipeline-cockpit och alla prenumeranter |

### Menysynlighet

| Meny | Admin | Användare | Prenumerant |
|---|:---:|:---:|:---:|
| Pipeline (cockpit) | ✓ | — | — |
| Prenumeranter — alla | ✓ | — | — |
| Min prenumeration | ✓ | ✓ | ✓ |
| Källor | ✓ | ✓ | — |
| Kö | ✓ | ✓ | — |
| Klara objekt | ✓ | ✓ | ✓ |
| Alla objekt | ✓ | ✓ | — |

### Vad Prenumerant/Användare kan göra

- **Min prenumeration** — se sin egen prenumerantrad, toggla aktiv/inaktiv,
  ändra e-postoverride, välja domäner (UFO/UAP, AI)
- **Sökord** — lägga till, ändra och ta bort egna sökord med vikt och domän
- **"Lägg till äldre utskick i kö"** — begära resend av ett tidigare digestdatum
- **Leveranshistorik** — se sina egna leveranser (read-only)
- **Klara objekt** — läsa alla indexerade bevakningsobjekt

### Record rules

Prenumerant- och Användargruppen begränsas av `ir.rule` så att de aldrig
ser andras data:

| Modell | Begränsning |
|---|---|
| `clio.vigil.subscriber` | `partner_id.user_ids` innehåller inloggad användare |
| `clio.vigil.keyword` | via `subscriber_id.partner_id.user_ids` |
| `clio.vigil.delivery` | via `subscriber_id.partner_id.user_ids` |
| `clio.vigil.resend.request` | via `subscriber_id.partner_id.user_ids` |

## Uppgradera på servern

```bash
docker exec odoo19-odoo-1 odoo -c /etc/odoo/odoo.conf \
  -u clio_vigil -d uap --stop-after-init
docker restart odoo19-odoo-1
```

## Beroenden

`contacts`, `clio_cockpit`
