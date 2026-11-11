# clio-slack-audit

Exporterar Slack Enterprise Grid-inställningar till daterade JSON-filer och en Markdown-rapport.
Deno + TypeScript, enbart läsande anrop — ingenting skrivs eller ändras i Slack.

## Krav

### Token

User OAuth Token (`xoxp-…`) med scopen nedan, **org-installerad av Org Owner**.
Samma app som `clio-scim-department` (`clio-slack-scim`) — lägg till scopen i appens manifest
och ominstallera som Org Owner för att få en ny token.

#### Scopen som måste läggas till appens manifest

```json
{
  "oauth_config": {
    "scopes": {
      "user": [
        "admin",
        "users:read",
        "users:read.email",
        "admin.teams:read",
        "admin.apps:read",
        "admin.conversations:read",
        "admin.barriers:read",
        "admin.users:read",
        "auditlogs:read",
        "channels:read",
        "team:read",
        "team.preferences:read",
        "users.profile:read"
      ]
    }
  }
}
```

**OBS:** `auditlogs:read` kräver att installatören är *Org Owner*, inte bara Org Admin.
Utan det scopet skrivs `missing_scope` för området "Audit log" i rapporten — exporten fortsätter.

### Deno

Deno 2.x. Installerat via `winget install DenoLand.Deno`.

## Användning

```powershell
copy .env.example .env   # fyll i SLACK_AUDIT_TOKEN=xoxp-...
deno task export
deno task test
```

Exporten hamnar i `export/<YYYY-MM-DD>/`:

| Fil | Innehåll |
|---|---|
| `01-org-info.json` | team.info + admin.teams.settings.info |
| `02-workspaces.json` | Workspaces i org med admins och owners |
| `03-apps.json` | Godkända och begränsade appar |
| `04-conversations.json` | Alla kanaler med prefs och retention per kanal |
| `05-barriers.json` | Informationsbarriärer |
| `06-emoji.json` | Custom emoji |
| `07-auth-policy.json` | Användare i email_password-policyn |
| `08-users.json` | Alla org-användare (is_admin, is_owner, has_2fa, has_sso) |
| `09-sessions.json` | Aktiva sessioner (device, OS, IP) |
| `10-profile-fields.json` | Profilfältsdefinitioner inkl. is_scim per fält |
| `11-workspace-prefs.json` | display_real_names, disable_file_uploads m.fl. |
| `12-scim-users.json` | Alla SCIM-användare inkl. Department |
| `13-scim-groups.json` | SCIM-grupper |
| `14-scim-config.json` | SCIM ServiceProviderConfig |
| `15-audit-recent.json` | Senaste 30 dagarnas audit-händelser (max 5 000) |
| `report.md` | Samlad rapport med täckning + manuell checklista |

Två körningar kan diffas: `diff export/2026-11-10/report.md export/2026-11-11/report.md`

## Vad som INTE täcks av API

| Inställning | Manuell kontroll |
|---|---|
| 2FA-krav på/av | Admin → Security → Two-factor authentication |
| SSO-läge (optional/required) | Admin → Security → Authentication |
| Org-default meddelanderetention | Admin → Data Management → Retention policies |
| Slack Connect-status | Admin → Org Settings → Slack Connect |
| Sessionstidsgräns | Admin → Security → Session duration |
| Vem får installera appar | Admin → Apps → App Management |
| Gästbegränsningar | Admin → Members → Guest access |
| EKM-status | Admin → Security → Key Management |
| Slack Atlas-inställningar | Admin → Atlas |
| DLP-integration | Admin → Data Management → DLP |
| Namnregler för kanaler | Admin → Org Settings → Channel naming |

Rapporten `report.md` listar alltid dessa punkter med var de finns.
