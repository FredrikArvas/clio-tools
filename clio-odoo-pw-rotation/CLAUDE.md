# clio-odoo-pw-rotation — CLAUDE.md

Roterar Odoo-lösenord för konton i `clio-tools/.env` via Odoos ORM
(`docker exec -i <container> odoo shell`, Python-koden skickas på stdin).

**NCC:** undersida till #odoo19, "Context Card — Odoo lösenordsrotation"
(Notion 41967666d98a81609378f87c7a850957). Status, logg och öppna punkter finns där.

## Körning (på servern)

```bash
cd ~/19.0/clio-tools/clio-odoo-pw-rotation
python3 rotate_passwords.py --instance odoo19            # torrkörning (standard)
python3 rotate_passwords.py --run --instance odoo19 [--db DB] [--login LOGIN]
python3 -m pytest tests -q
```

Status: OK · OK_UNVERIFIED · SKIPPED (kontot finns inte) · WOULD_CHANGE · FAIL.
Exit 1 vid FAIL eller OK_UNVERIFIED.

## Regler

- Lösenord får aldrig hamna i argument, processlista, loggar eller terminal.
  De bäddas in i Python-koden med `repr()` och skickas på stdin.
- Byt via `user.write({'password': ...})`, aldrig rå SQL mot `res_users`.
- Gör inga skarpa byten (`--run`) utan Fredriks uttryckliga ja.
- Kolla före rotation att inga integrationer (`ODOO_USER`/`ODOO_PASSWORD` i
  `.env`-filerna) loggar in med kontot. Annars går de sönder.

## Gotchas

- Odoo 19: `odoo shell --config ...` (underkommandot först).
  `_set_password()` tar inga argument.
  `_check_credentials(credential_dict, env)` kontrollerar `self.env.user`,
  så anropet måste gå via `with_user(user)` och inte `sudo()`.
- PowerShell lägger till BOM (U+FEFF) när den skickar data via stdin till ssh/docker.
  Kör från Bash eller på servern.
- Odoo 18 (`odoo-odoo-1`) har DB-uppgifterna i miljövariabler. `odoo shell` måste
  köras via `/entrypoint.sh`. Det är inte åtgärdat i skriptet ännu.
- Serverkopian i `~/19.0/clio-tools` är ospårad (scp:ad). Synka efter ändringar.
