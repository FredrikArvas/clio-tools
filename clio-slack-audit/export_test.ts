/**
 * export_test.ts — Enhetstester utan nätverk (fetch mockas).
 * Kör: deno task test
 */

import { assertEquals, assertRejects } from "@std/assert";
import { ApiError, SlackClient, SOFT_ERROR_CODES } from "./client.ts";
import { collectOrgInfo, collectBarriers, collectAuditLogs } from "./collectors.ts";
import { generateReport } from "./export.ts";

// ── Fake fetch ────────────────────────────────────────────────────────────────

type CallRecord = { url: string; method: string };

function fakeFetch(responses: Response[]) {
  const calls: CallRecord[] = [];
  const fetchFn = (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(input), method: init?.method ?? "GET" });
    const next = responses.shift();
    if (!next) throw new Error("Oväntat anrop: " + String(input));
    return Promise.resolve(next);
  };
  return { calls, fetchFn: fetchFn as typeof fetch };
}

const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(body), { status, headers });
const noSleep = () => Promise.resolve();
const TOKEN = "xoxp-test-token";

function client(responses: Response[]) {
  const fake = fakeFetch(responses);
  return {
    slack: new SlackClient({ token: TOKEN, fetchFn: fake.fetchFn, sleepFn: noSleep }),
    calls: fake.calls,
  };
}

// ── SlackClient — Web API ─────────────────────────────────────────────────────

Deno.test("call returnerar JSON vid ok:true", async () => {
  const { slack } = client([json({ ok: true, team: { id: "T123" } })]);
  const r = await slack.call("team.info");
  assertEquals((r.team as Record<string, unknown>)?.id, "T123");
});

Deno.test("call kastar ApiError vid ok:false", async () => {
  const { slack } = client([json({ ok: false, error: "missing_scope" })]);
  const err = await assertRejects(() => slack.call("admin.teams.list"), ApiError);
  assertEquals(err.code, "missing_scope");
  assertEquals(err.isSoft, true);
});

Deno.test("call kastar ApiError med isSoft=false för okänd error", async () => {
  const { slack } = client([json({ ok: false, error: "invalid_auth" })]);
  const err = await assertRejects(() => slack.call("team.info"), ApiError);
  assertEquals(err.isSoft, false);
});

Deno.test("429 med retry-after görs om och lyckas", async () => {
  const { slack, calls } = client([
    json({}, 429, { "retry-after": "1" }),
    json({ ok: true, teams: [] }),
  ]);
  await slack.call("admin.teams.list");
  assertEquals(calls.length, 2);
});

Deno.test("upprepade 429 kastar ApiError", async () => {
  const { slack } = client(
    Array.from({ length: 4 }, () => json({}, 429, { "retry-after": "1" })),
  );
  await assertRejects(() => slack.call("admin.teams.list"), ApiError);
});

// ── SlackClient — paginering ──────────────────────────────────────────────────

Deno.test("paginate hämtar flera sidor via cursor", async () => {
  const { slack } = client([
    json({ ok: true, teams: [{ id: "T1" }], response_metadata: { next_cursor: "abc" } }),
    json({ ok: true, teams: [{ id: "T2" }], response_metadata: { next_cursor: "" } }),
  ]);
  const pages: unknown[][] = [];
  for await (const page of slack.paginate("admin.teams.list")) {
    pages.push((page.teams as unknown[]) ?? []);
  }
  assertEquals(pages.flat().length, 2);
});

Deno.test("paginate stannar utan cursor", async () => {
  const { slack } = client([json({ ok: true, teams: [{ id: "T1" }] })]);
  const pages: unknown[] = [];
  for await (const page of slack.paginate("admin.teams.list")) {
    pages.push(page);
  }
  assertEquals(pages.length, 1);
});

// ── SlackClient — SCIM ────────────────────────────────────────────────────────

Deno.test("scimPaginate hämtar alla sidor tills returned < count", async () => {
  const { slack } = client([
    json({ Resources: [{ id: "U1" }, { id: "U2" }], totalResults: 3 }),
    json({ Resources: [{ id: "U3" }], totalResults: 3 }),
  ]);
  const users: unknown[] = [];
  for await (const page of slack.scimPaginate("Users", 2)) {
    users.push(...((page.Resources as unknown[]) ?? []));
  }
  assertEquals(users.length, 3);
});

// ── Collectors ────────────────────────────────────────────────────────────────

Deno.test("collectOrgInfo returnerar team_info och teams_settings_info", async () => {
  const { slack } = client([
    json({ ok: true, team: { id: "T123", name: "TestOrg" } }),
    json({ ok: true, team: { id: "T123", default_channels: [] } }),
  ]);
  const r = await collectOrgInfo(slack);
  assertEquals(r.error, undefined);
  const data = r.data as Record<string, unknown>;
  assertEquals((data.team_info as Record<string, unknown>)?.id, "T123");
});

Deno.test("collectOrgInfo rapporterar missing_scope utan att krascha", async () => {
  const { slack } = client([
    json({ ok: true, team: { id: "T123" } }),
    json({ ok: false, error: "missing_scope" }),
  ]);
  const r = await collectOrgInfo(slack);
  // admin.teams.settings.info misslyckas, men collectOrgInfo ska fortfarande lyckas
  assertEquals(r.error, undefined);
  const data = r.data as Record<string, unknown>;
  assertEquals((data.teams_settings_info as Record<string, unknown>)?._error, "missing_scope");
});

Deno.test("collectBarriers rapporterar feature_not_enabled", async () => {
  const { slack } = client([
    json({ ok: false, error: "feature_not_enabled" }),
  ]);
  const r = await collectBarriers(slack);
  assertEquals(r.error, "feature_not_enabled");
  assertEquals(r.data, null);
});

Deno.test("collectBarriers kastar vid hård fel", async () => {
  const { slack } = client([
    json({ ok: false, error: "invalid_auth" }),
  ]);
  await assertRejects(() => collectBarriers(slack), ApiError);
});

// ── Audit log ─────────────────────────────────────────────────────────────────

Deno.test("collectAuditLogs returnerar entries från GET-svar", async () => {
  const { slack } = client([
    new Response(
      JSON.stringify({ entries: [{ id: "e1", action: "pref.two_factor_auth_changed" }] }),
      { status: 200 },
    ),
  ]);
  const r = await collectAuditLogs(slack);
  assertEquals(r.error, undefined);
  assertEquals((r.data as unknown[]).length, 1);
});

Deno.test("collectAuditLogs rapporterar missing_scope", async () => {
  const { slack } = client([new Response(JSON.stringify({ error: "missing_scope" }), { status: 403 })]);
  const r = await collectAuditLogs(slack);
  assertEquals(r.error, "missing_scope");
});

// ── Rapport ───────────────────────────────────────────────────────────────────

Deno.test("generateReport innehåller alla rubriker och resultat", () => {
  const results = [
    { area: "Org-info", file: "01-org-info", data: {}, count: undefined },
    { area: "Barriers", file: "05-barriers", data: null, error: "feature_not_enabled" },
  ];
  const report = generateReport(results, "2026-11-11");
  assertEquals(report.includes("2026-11-11"), true);
  assertEquals(report.includes("✅"), true);
  assertEquals(report.includes("❌"), true);
  assertEquals(report.includes("feature_not_enabled"), true);
  assertEquals(report.includes("Kräver manuell kontroll"), true);
});

Deno.test("SOFT_ERROR_CODES innehåller missing_scope och feature_not_enabled", () => {
  assertEquals(SOFT_ERROR_CODES.has("missing_scope"), true);
  assertEquals(SOFT_ERROR_CODES.has("feature_not_enabled"), true);
  assertEquals(SOFT_ERROR_CODES.has("invalid_auth"), false);
});
