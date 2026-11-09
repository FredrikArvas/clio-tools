/**
 * cli.ts
 * Kommandorad för Department-CRUD via Slack SCIM.
 *
 * Usage:
 *     deno task dept get    <e-post|Slack-ID>
 *     deno task dept set    <e-post|Slack-ID> "<värde>" [--apply]
 *     deno task dept delete <e-post|Slack-ID>           [--apply]
 *
 * Utan --apply visas bara före/efter (dry-run). Inget skrivs.
 *
 * Environment (.env i modulmappen, aldrig i git):
 *     SLACK_SCIM_TOKEN  – xoxp-token med scopen admin, installerad av Org Owner
 */

import { ScimDepartmentClient, ScimError } from "./department.ts";

// ── Configuration ─────────────────────────────────────────────────────────────

export const VERSION = "0.1.0";
const TOKEN_VARIABLE = "SLACK_SCIM_TOKEN";
const USAGE = `clio-slack-scim ${VERSION}
  get    <e-post|Slack-ID>
  set    <e-post|Slack-ID> "<värde>" [--apply]
  delete <e-post|Slack-ID>           [--apply]`;

// ── Logging ───────────────────────────────────────────────────────────────────

function log(level: "INFO" | "WARNING" | "ERROR", message: string): void {
  const timestamp = new Date().toISOString().replace("T", " ").slice(0, 19);
  const line = `${timestamp}  ${level.padEnd(8)}  ${message}`;
  if (level === "ERROR") console.error(line);
  else console.log(line);
}

// ── Commands ──────────────────────────────────────────────────────────────────

export interface ParsedArguments {
  command: "get" | "set" | "delete";
  identifier: string;
  value?: string;
  isApply: boolean;
}

export function parseArguments(argumentList: string[]): ParsedArguments {
  const isApply = argumentList.includes("--apply");
  const positional = argumentList.filter((argument) => argument !== "--apply");
  const [command, identifier, value] = positional;
  if (command !== "get" && command !== "set" && command !== "delete") {
    throw new Error(USAGE);
  }
  if (!identifier) throw new Error(USAGE);
  if (command === "set" && value === undefined) throw new Error(USAGE);
  if (command !== "set" && positional.length > 2) throw new Error(USAGE);
  return { command, identifier, value, isApply };
}

export async function runCommand(
  client: ScimDepartmentClient,
  parsed: ParsedArguments,
): Promise<void> {
  const userId = await client.resolveUserId(parsed.identifier);
  const current = await client.getDepartment(userId);
  log("INFO", `${parsed.identifier} (${userId}) department: ${JSON.stringify(current)}`);
  if (parsed.command === "get") return;

  const target = parsed.command === "set" ? parsed.value!.trim() : null;
  if (current === target) {
    log("INFO", "Skipping – värdet är redan rätt.");
    return;
  }
  log("INFO", `Ändring: ${JSON.stringify(current)} → ${JSON.stringify(target)}`);
  if (!parsed.isApply) {
    log("INFO", "Dry-run – kör igen med --apply för att skriva.");
    return;
  }
  if (parsed.command === "set") await client.setDepartment(userId, parsed.value!);
  else await client.deleteDepartment(userId);

  const after = await client.getDepartment(userId);
  if (after !== target) {
    throw new Error(`Verifiering misslyckades: Slack visar ${JSON.stringify(after)}`);
  }
  log("INFO", `OK -> department är nu ${JSON.stringify(after)}`);
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main(): Promise<number> {
  let parsed: ParsedArguments;
  try {
    parsed = parseArguments(Deno.args);
  } catch (error) {
    console.error((error as Error).message);
    return 1;
  }
  const token = Deno.env.get(TOKEN_VARIABLE);
  if (!token) {
    log("ERROR", `${TOKEN_VARIABLE} saknas i .env`);
    return 1;
  }
  try {
    await runCommand(new ScimDepartmentClient({ token }), parsed);
    return 0;
  } catch (error) {
    if (error instanceof ScimError) {
      log("ERROR", `${error.message}: ${error.detail}`);
    } else {
      log("ERROR", (error as Error).message);
    }
    return 1;
  }
}

if (import.meta.main) {
  Deno.exit(await main());
}
