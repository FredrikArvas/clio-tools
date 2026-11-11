# CLAUDE.md — clio-slack-audit

Kontext för LLM-assistenter. Användning och bakgrund finns i README.md.

## Vad modulen är

Deno + TypeScript-verktyg som exporterar Slack Enterprise Grid-inställningar till
daterade JSON-filer och en Markdown-rapport. Byggt 2026-11-11 för NCC `capslack`.
Enbart läsande anrop — ingenting skrivs eller ändras i Slack.

| Fil | Ansvar |
|---|---|
| `client.ts` | `SlackClient`: Web API (call/paginate), Audit Logs API (auditPaginate), SCIM v2 (scimPaginate/scimGet). Injektabelt fetch och sleep. Hanterar 429/retry-after. |
| `collectors.ts` | En async-funktion per område → `CollectorResult`. `safeCollect` fångar mjuka API-fel (missing_scope, feature_not_enabled m.fl.) utan att krascha exporten. `collectAll` kör alla sekventiellt. |
| `export.ts` | CLI-ingångspunkt. Läser SLACK_AUDIT_TOKEN, kör collectAll, skriver JSON-filer + report.md. Exporterar även `generateReport` för tester. |
| `export_test.ts` | Enhetstester med mockad fetch. Täcker retry, paginering, mjuka fel, rapport. |

## Förutsättningar

- **Deno 2.x**
- **Token** i `.env` (gitignorerad): `SLACK_AUDIT_TOKEN=xoxp-…`
  - **Separat app** `clio-slack-audit` — inte samma som `clio-scim-department`.
  - Installeras av **Org Owner** på org-nivå (krävs för `auditlogs:read`).
  - Listas aldrig i chatten, loggas aldrig, skrivs aldrig i kod.
- **Scopen** som krävs: se README.md. `auditlogs:read` kräver Org Owner vid install.

## Regler

- Inga skrivoperationer — aldrig add/update/delete mot Slack API.
- Mjukt fel (missing_scope, feature_not_enabled m.fl.) → `CollectorResult.error` sätts; exporten fortsätter och rapporterar felet. Hård fel (invalid_auth, nätverksfel) → kraschar och visas för användaren.
- `export/`-mappen är gitignorerad (kan innehålla PII och org-data).
- Tokens läses aldrig in i chatten.
- `deno.json` begränsar nätverk till `slack.com,api.slack.com`, filsystemet till `export/`, och miljö till `SLACK_AUDIT_TOKEN`.

## Kommandon

```powershell
deno task export     # kör export mot Slack, skriver export/<datum>/
deno task test       # kör enhetstester (inget nätverk)
deno lint; deno check export.ts
```

## Fällor

- `auditlogs:read` kräver Org Owner vid install. Om token saknar scopet returneras `missing_scope` för audit-området — exporten fortsätter.
- `channels:read` behövs för `conversations.list`. Om det saknas försöker kollektorn med `admin.conversations.search` (tom query). Om båda misslyckas skrivs `_error` på resultatet.
- SCIM använder Bearer-autentisering med samma xoxp-token som Web API — det är korrekt för Slack.
- Enterprise Grid kräver org-installerad token (`is_enterprise_install: true` i `auth.test`).

## Öppet

- Per-kanal prefs/retention är O(n) anrop — funkar för testorgen, kan behöva begränsas för org med 1 000+ kanaler.
- `admin.users.session.list` utan user_id/team_id returnerar alla sessioner — kan bli stort på stor org.
- Workflow Builder-steg (Deno Slack SDK) för automatisk schemalagd export.
