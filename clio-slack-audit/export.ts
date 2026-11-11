/**
 * export.ts — CLI-ingångspunkt för clio-slack-audit.
 *
 * Usage:
 *   deno task export
 *
 * Skriver export/<YYYY-MM-DD>/<fil>.json och export/<YYYY-MM-DD>/report.md.
 *
 * Environment (.env i modulmappen, aldrig i git):
 *   SLACK_AUDIT_TOKEN — xoxp-token med utökade scopes, org-installerad av Org Owner.
 *   Se README.md för krav.
 */

import { join } from "@std/path";
import { ensureDir } from "@std/fs";
import { SlackClient } from "./client.ts";
import { collectAll, type CollectorResult } from "./collectors.ts";

const TOKEN_VAR = "SLACK_AUDIT_TOKEN";
const MANUAL_CHECKS = [
  { setting: "2FA-krav på org-nivå (på/av)", where: "Admin → Security → Two-factor authentication", note: "Audit log loggar *ändringar* (pref.two_factor_auth_changed), inte nuläge" },
  { setting: "SSO-läge (optional/required/disabled)", where: "Admin → Security → Authentication", note: "Audit log loggar *ändringar* (pref.sso_setting_changed), inte nuläge" },
  { setting: "Org-default meddelanderetention", where: "Admin → Data Management → Retention policies", note: "Ingen API-metod för org-default; per-kanal täcks av 04-conversations.json" },
  { setting: "Slack Connect-status (på/av)", where: "Admin → Org Settings → Slack Connect", note: "Ingen läs-API" },
  { setting: "Sessionstidsgräns (org-nivå)", where: "Admin → Security → Session duration", note: "Ingen API" },
  { setting: "Vem får installera appar (org-policy)", where: "Admin → Apps → App Management", note: "admin.apps.* listar godkända/blockerade appar, men inte vem-får-be-policyn" },
  { setting: "Gästbegränsningar", where: "Admin → Members → Guest access", note: "Ingen läs-API" },
  { setting: "EKM-status", where: "Admin → Security → Key Management", note: "Inget publikt read-API" },
  { setting: "Slack Atlas-inställningar", where: "Admin → Atlas", note: "Ingen API" },
  { setting: "DLP-integration", where: "Admin → Data Management → DLP", note: "Ingen API" },
  { setting: "Namnregler för kanaler", where: "Admin → Org Settings → Channel naming", note: "Ingen API" },
];

function dateStamp(): string {
  return new Date().toISOString().slice(0, 10);
}

function generateReport(results: CollectorResult[], stamp: string): string {
  const lines: string[] = [
    `# Slack Enterprise Export — cap-migration-test`,
    ``,
    `**Datum:** ${stamp}  `,
    `**Org:** E0C4PR85XTM  `,
    `**Workspace:** T0C9PDSAX96 — Cap Migration Capacity Test`,
    ``,
    `---`,
    ``,
    `## API-täckning`,
    ``,
    `| Område | Status | Poster | Fil |`,
    `|---|---|---|---|`,
  ];

  for (const r of results) {
    const status = r.error ? `❌ \`${r.error}\`` : "✅";
    const count = r.count !== undefined ? String(r.count) : "—";
    const file = r.error ? "—" : `${r.file}.json`;
    lines.push(`| ${r.area} | ${status} | ${count} | ${file} |`);
  }

  lines.push(
    ``,
    `---`,
    ``,
    `## ⚠️ Kräver manuell kontroll`,
    ``,
    `Följande inställningar kan inte hämtas via Slack API och måste stämmas av i admin-gränssnittet.`,
    ``,
    `| Inställning | Var | Notering |`,
    `|---|---|---|`,
  );
  for (const { setting, where, note } of MANUAL_CHECKS) {
    lines.push(`| ${setting} | ${where} | ${note} |`);
  }

  const missedScopes = results.filter((r) => r.error === "missing_scope");
  if (missedScopes.length > 0) {
    lines.push(
      ``,
      `---`,
      ``,
      `## 🔑 Saknade scopes`,
      ``,
      `Följande områden returnerade \`missing_scope\`. Lägg till scopet i appens manifest och ominstallera som Org Owner.`,
      ``,
      `| Område | Saknat scope |`,
      `|---|---|`,
    );
    for (const r of missedScopes) {
      lines.push(`| ${r.area} | Se README.md |`);
    }
  }

  lines.push(``, `---`, ``, `*Genererad av clio-slack-audit. Körningsformat: JSON per område + denna rapport.*`);
  return lines.join("\n");
}

async function main(): Promise<number> {
  const token = Deno.env.get(TOKEN_VAR);
  if (!token) {
    console.error(`${TOKEN_VAR} saknas i .env`);
    return 1;
  }

  const stamp = dateStamp();
  const exportDir = join("export", stamp);
  await ensureDir(exportDir);

  const client = new SlackClient({ token });

  console.log(`Exporterar till ${exportDir}/...`);
  const results = await collectAll(client);

  for (const r of results) {
    const icon = r.error ? "✗" : "✓";
    const detail = r.error
      ? ` (${r.error})`
      : r.count !== undefined
      ? ` (${r.count} poster)`
      : "";
    console.log(`  ${icon} ${r.area}${detail}`);

    if (!r.error) {
      const path = join(exportDir, `${r.file}.json`);
      await Deno.writeTextFile(path, JSON.stringify(r.data, null, 2));
    }
  }

  const reportPath = join(exportDir, "report.md");
  await Deno.writeTextFile(reportPath, generateReport(results, stamp));
  console.log(`\nRapport: ${reportPath}`);

  const failed = results.filter((r) => r.error).length;
  if (failed > 0) {
    console.log(`\n${failed} område(n) misslyckades — se rapport för detaljer.`);
  }
  return 0;
}

if (import.meta.main) {
  Deno.exit(await main());
}

export { generateReport };
