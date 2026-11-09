# CLAUDE.md — clio-slack-scim

Kontext för LLM-assistenter. Användning och bakgrund finns i README.md.

## Vad modulen är

Deno + TypeScript-verktyg som läser, sätter och tar bort SCIM-fältet
**Department** för Slack-användare (Business+ / Enterprise Grid). Byggt
2026-11-09 för NCC `capslack`; testat mot Enterprise-testorgen
`cap-migration-test` (E0C4PR85XTM).

| Fil | Ansvar |
|---|---|
| `department.ts` | Kärnan: `ScimDepartmentClient` (resolve/get/set/delete). Ingen CLI-logik, injicerbar `fetch` – ska kunna flyttas in i ett Workflow Builder-steg (Deno Slack SDK) oförändrad. |
| `cli.ts` | Argumenttolkning, dry-run/`--apply`, verifiering efter skrivning, loggning. |
| `department_test.ts` | Enhetstester med mockad fetch, inga nätverksanrop. |

## Förutsättningar

- **Deno 2.x** (installerat via `winget install DenoLand.Deno` på EliteBook2). Starta om skalet eller läs om PATH efter installation.
- **Token** i `.env` (gitignorerad): `SLACK_SCIM_TOKEN=xoxp-…`
  - User OAuth Token med scopes `admin`, `users:read`, `users:read.email`.
  - På Enterprise Grid **måste** appen vara installerad på organisationen
    (Access Level: Org, `auth.test` → `is_enterprise_install: true`).
  - Appen skapas från manifestet i README.md (`org_deploy_enabled: true`).
- Token läses aldrig in i chatten, loggas aldrig och skrivs aldrig i kod.

## Kommandon

```powershell
deno task dept get    <e-post|Slack-ID>
deno task dept set    <e-post|Slack-ID> "<värde>" [--apply]
deno task dept delete <e-post|Slack-ID>           [--apply]
deno task test
deno lint; deno check cli.ts
```

## Regler och fällor

- **Dry-run är standard.** Skrivningar kräver `--apply` och verifieras med en ny `GET`. Ändra inte det beteendet.
- **Department är envärt.** Ger användaren två värden för samma person – fråga vilket som gäller i stället för att skriva båda.
- **SCIM v1 fungerar inte på Grid** (`non_org_teams_only`). Använd bara `/scim/v2/`.
- **Workspace-token ger `unsupported_version` på v2** – det betyder fel installationsnivå, inte fel kod.
- **"Install to organization" är grå** så länge appen är installerad på ett workspace. Avinstallera från workspacet först.
- **E-postuppslag** går via `users.lookupByEmail` (v2 saknar dokumenterat e-postfilter). `missing_scope` = token saknar `users:read.email`.
- Department är kopplat till datakällan **SCIM** i Slack Atlas. Byts källan till API måste `users.profile.set` användas i stället.
- `deno.json` begränsar nätverk till `api.slack.com,slack.com` och miljö till `SLACK_SCIM_TOKEN` – utöka inte i onödan.
- `.env.example` är force-adderad (`.env.*` står i `.gitignore`); håll den fri från hemligheter.

## Säkerhet

Org-token med `admin` kan administrera *alla* användare i organisationen
(inaktivera, ändra e-post m.m.), inte bara Department. Använd den bara mot
testorgen tills kunden fattat ett riskbeslut, och rotera/avinstallera efter test.

## Öppet

- Workflow Builder-steg (Deno Slack SDK) – kräver Slack CLI och ett beslut om var org-token får förvaras.
- Fler SCIM-fält (division m.fl.) – samma mönster, generalisera `DEPARTMENT_PATH`.
- Organization-fältet har datakälla API (Field ID i Atlas) och kräver `users.profile.set`.
