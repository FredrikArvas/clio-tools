# clio_cockpit — Clio Kontrollpanel

Samlad Odoo-vy för alla Clio-agenter och tjänster på elitedeskgpu.

## Flikar och behörigheter

| Flik | Innehåll | Behörighet |
|---|---|---|
| 🤖 Agenter | Agentstatus (mail, service, rag) | `group_clio_user` |
| 🔍 RAG | Frågor mot kunskapsbasen | Öppen (`base.group_user`) |
| 📚 Bibliotek | Sök i indexerade böcker | Öppen (`base.group_user`) |
| 📧 Mail Admin | Vitlista, svartlista, intervjuer | `group_clio_admin` |
| 🖥️ Server | CPU, RAM, disk, uppdateringar | `group_clio_admin` |

### Grupper

- **Clio User** (`group_clio_user`) — kan se agenter + öppna flikar
- **Clio Admin** (`group_clio_admin`) — ärver User, ser mail admin + server

Fredrik (admin/root) läggs automatiskt i Clio Admin vid installation.

---

## Beroenden — externa tjänster

Cockpit kommunicerar med `clio-service` via HTTP (konfigureras i
`ir.config_parameter` → nyckel: `clio.service.url`).

### Tjänster och moduler som används

| Tjänst / Modul | Port | Syfte | Fil |
|---|---|---|---|
| **clio-service** | 7200 | Routing av alla Cockpit-anrop | `clio-agent-mail/clio_service.py` |
| **clio-agent-mail** | systemd | E-post in/ut, projekt, intervjuer | `clio-agent-mail/` |
| **clio-rag (Qdrant)** | 6333 | Vektorsök i böcker och NCC | `clio-rag/` |
| **clio-agent-odoo** | 8100 | Clio i Odoo Discuss (#Clio-kanalen) | `clio-agent-odoo/` |

### Planerade integrationer

| Modul / Tjänst | Status | Anteckning |
|---|---|---|
| **clio-graph (Neo4j)** | Aktiv, ej i Cockpit | Graf-relationer GSF-partners. Port 7474/7687. Lägg till flik "Graf" |
| **clio-agent-job** | Aktiv | Jobbannonsbevakning. Kan få flik i Mail Admin |
| **clio-agent-obit** | Aktiv | Dödsannonsbevakning. Kan samlas med agent-job |
| **Loggar** | Ej byggt | Visa `/tmp/clio-*.log` via clio-service `/logs` endpoint |
| **Clio Discuss (v2)** | Planerad | Kontextbaserad chatter per Odoo-objekt |

### Docker gateway

Från Odoo-containern nås host via `172.18.0.1` (Docker bridge gateway).
UFW-regler krävs per port:
```bash
sudo ufw allow from 172.18.0.0/16 to any port 7200
sudo ufw allow from 172.18.0.0/16 to any port 8100
```

---

## Installation / Uppgradering

```bash
docker exec odoo-odoo-1 odoo -c /etc/odoo/odoo.conf \
  -d aiab -u clio_cockpit --stop-after-init \
  --db_host=db --db_user=odoo --db_password=odoo
docker compose restart odoo
```
