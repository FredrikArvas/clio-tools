# clio-slack-scim

Läser, sätter och tar bort SCIM-fältet **Department** för Slack-användare
(Business+ / Enterprise Grid). Deno + TypeScript, inga beroenden utöver
`@std/assert` i testerna. Kärnan (`department.ts`) är fri från CLI-logik och
kan återanvändas i ett Workflow Builder-steg (Deno Slack SDK).

## Krav på token

- User OAuth Token (`xoxp-…`) med scopes `admin`, `users:read`, `users:read.email`
- **Enterprise Grid:** appen måste installeras på *organisationen* av en Org Owner
  (Access Level: Org). En workspace-token ger `non_org_teams_only` (SCIM v1)
  och `unsupported_version` (SCIM v2).
- Den gråa knappen "Install to organization" låstes upp först när appen
  avinstallerats från workspacet.

Manifest för appen:

```json
{
  "display_information": { "name": "clio-scim-department" },
  "oauth_config": { "scopes": { "user": ["admin", "users:read", "users:read.email"] } },
  "settings": { "org_deploy_enabled": true, "token_rotation_enabled": false }
}
```

## Användning

```powershell
copy .env.example .env      # fyll i SLACK_SCIM_TOKEN
deno task dept get    anna@example.com
deno task dept set    anna@example.com "Ekonomi"            # dry-run
deno task dept set    anna@example.com "Ekonomi" --apply
deno task dept delete anna@example.com --apply
deno task test
```

Användare anges med e-post (slås upp med `users.lookupByEmail`) eller Slack-ID.
Skrivningar kräver `--apply` och verifieras med en ny läsning efteråt.
429-svar respekterar `retry-after`.

## Hur det fungerar

| Operation | Anrop |
|---|---|
| Läs | `GET /scim/v2/Users/{id}` → `urn:ietf:params:scim:schemas:extension:enterprise:2.0:User.department` |
| Sätt/ändra | `PATCH` PatchOp `add` på `…enterprise:2.0:User:department` |
| Ta bort | `PATCH` PatchOp `remove` på samma path |

Verifierat mot Enterprise Grid-testorg 2026-11-09 (set, ändra, ta bort, läs).

## Säkerhet

Org-token kan administrera alla användare i organisationen (inte bara
Department). Förvara den bara i `.env` (gitignorerad), dela den aldrig i chatt
och rotera den när testet är klart.
