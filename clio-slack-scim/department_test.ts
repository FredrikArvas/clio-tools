/**
 * department_test.ts — enhetstester utan nätverk (fetch mockas).
 * Kör: deno task test
 */

import { assertEquals, assertRejects, assertThrows } from "@std/assert";
import {
  DEPARTMENT_PATH,
  ENTERPRISE_SCHEMA,
  PATCH_SCHEMA,
  ScimDepartmentClient,
  ScimError,
  validateDepartment,
} from "./department.ts";
import { parseArguments, runCommand } from "./cli.ts";

// ── Fake fetch ────────────────────────────────────────────────────────────────

interface RecordedCall {
  url: string;
  method: string;
  body: unknown;
  authorization: string | null;
}

function fakeFetch(responses: Response[]) {
  const calls: RecordedCall[] = [];
  const fetchFunction = (input: string | URL | Request, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      authorization: headers.get("Authorization"),
    });
    const next = responses.shift();
    if (!next) throw new Error("Oväntat anrop: " + String(input));
    return Promise.resolve(next);
  };
  return { calls, fetchFunction: fetchFunction as typeof fetch };
}

const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(body), { status, headers });
const userWith = (department?: string) => ({
  id: "W0123ABCD",
  [ENTERPRISE_SCHEMA]: department === undefined ? {} : { department },
});
const TOKEN = "xoxp-test-token";
const noSleep = () => Promise.resolve();

function client(responses: Response[]) {
  const fake = fakeFetch(responses);
  const scimClient = new ScimDepartmentClient({
    token: TOKEN,
    fetchFunction: fake.fetchFunction,
    sleepFunction: noSleep,
  });
  return { scimClient, calls: fake.calls };
}

// ── Validering ────────────────────────────────────────────────────────────────

Deno.test("validateDepartment trimmar giltigt värde", () => {
  assertEquals(validateDepartment("  Ekonomi  "), "Ekonomi");
});

Deno.test("validateDepartment avvisar tomt, för långt och kontrolltecken", () => {
  assertThrows(() => validateDepartment("   "));
  assertThrows(() => validateDepartment("x".repeat(257)));
  assertThrows(() => validateDepartment("Ekonomi\nIT"));
});

Deno.test("konstruktorn avvisar bot-token", () => {
  assertThrows(() => new ScimDepartmentClient({ token: "xoxb-bot" }));
});

// ── Uppslag ───────────────────────────────────────────────────────────────────

Deno.test("resolveUserId returnerar Slack-ID utan anrop", async () => {
  const { scimClient, calls } = client([]);
  assertEquals(await scimClient.resolveUserId("W0123ABCD"), "W0123ABCD");
  assertEquals(calls.length, 0);
});

Deno.test("resolveUserId slår upp e-post via users.lookupByEmail", async () => {
  const { scimClient, calls } = client([json({ ok: true, user: { id: "U0999XYZ" } })]);
  assertEquals(await scimClient.resolveUserId("a.b@arvas.se"), "U0999XYZ");
  assertEquals(calls[0].url, "https://slack.com/api/users.lookupByEmail?email=a.b%40arvas.se");
  assertEquals(calls[0].authorization, `Bearer ${TOKEN}`);
});

Deno.test("resolveUserId ger 404 när användaren saknas", async () => {
  const { scimClient } = client([json({ ok: false, error: "users_not_found" })]);
  const error = await assertRejects(
    () => scimClient.resolveUserId("saknas@arvas.se"),
    ScimError,
  );
  assertEquals(error.status, 404);
});

Deno.test("resolveUserId rapporterar saknad scope och ogiltig indata", async () => {
  const { scimClient } = client([json({ ok: false, error: "missing_scope" })]);
  const error = await assertRejects(
    () => scimClient.resolveUserId("a.b@arvas.se"),
    ScimError,
  );
  assertEquals(error.detail, "missing_scope");
  await assertRejects(() => scimClient.resolveUserId('x" or "1'), Error);
});

// ── CRUD ──────────────────────────────────────────────────────────────────────

Deno.test("getDepartment läser enterprise-extensionen", async () => {
  const { scimClient } = client([json(userWith("Försäljning")), json(userWith())]);
  assertEquals(await scimClient.getDepartment("W0123ABCD"), "Försäljning");
  assertEquals(await scimClient.getDepartment("W0123ABCD"), null);
});

Deno.test("setDepartment skickar PatchOp add på department-pathen", async () => {
  const { scimClient, calls } = client([json(userWith("IT"))]);
  await scimClient.setDepartment("W0123ABCD", " IT ");
  assertEquals(calls[0].method, "PATCH");
  assertEquals(calls[0].url, "https://api.slack.com/scim/v2/Users/W0123ABCD");
  assertEquals(calls[0].body, {
    schemas: [PATCH_SCHEMA],
    Operations: [{ op: "add", path: DEPARTMENT_PATH, value: "IT" }],
  });
});

Deno.test("deleteDepartment skickar PatchOp remove", async () => {
  const { scimClient, calls } = client([new Response(null, { status: 204 })]);
  await scimClient.deleteDepartment("W0123ABCD");
  assertEquals(calls[0].body, {
    schemas: [PATCH_SCHEMA],
    Operations: [{ op: "remove", path: DEPARTMENT_PATH }],
  });
});

// ── Fel och rate limits ───────────────────────────────────────────────────────

Deno.test("429 med retry-after görs om och lyckas", async () => {
  const { scimClient, calls } = client([
    json({}, 429, { "retry-after": "1" }),
    json(userWith("IT")),
  ]);
  assertEquals(await scimClient.getDepartment("W0123ABCD"), "IT");
  assertEquals(calls.length, 2);
});

Deno.test("upprepade 429 ger ScimError", async () => {
  const { scimClient } = client(
    Array.from({ length: 4 }, () => json({}, 429, { "retry-after": "1" })),
  );
  await assertRejects(() => scimClient.getDepartment("W0123ABCD"), ScimError);
});

Deno.test("401 ger ScimError med Slacks felbeskrivning", async () => {
  const { scimClient } = client([
    json({ Errors: { code: 401, description: "invalid_authentication" } }, 401),
  ]);
  const error = await assertRejects(
    () => scimClient.getDepartment("W0123ABCD"),
    ScimError,
  );
  assertEquals(error.status, 401);
  assertEquals(error.detail, "invalid_authentication");
});

// ── CLI ───────────────────────────────────────────────────────────────────────

Deno.test("parseArguments tolkar kommandon och --apply", () => {
  assertEquals(parseArguments(["set", "W0123ABCD", "IT", "--apply"]), {
    command: "set",
    identifier: "W0123ABCD",
    value: "IT",
    isApply: true,
  });
  assertThrows(() => parseArguments(["set", "W0123ABCD"]));
  assertThrows(() => parseArguments(["drop", "W0123ABCD"]));
  assertThrows(() => parseArguments(["get"]));
});

Deno.test("runCommand dry-run läser men skriver inte", async () => {
  const { scimClient, calls } = client([json(userWith("Gammal"))]);
  await runCommand(scimClient, parseArguments(["set", "W0123ABCD", "Ny"]));
  assertEquals(calls.map((call) => call.method), ["GET"]);
});

Deno.test("runCommand --apply skriver och verifierar", async () => {
  const { scimClient, calls } = client([
    json(userWith("Gammal")),
    json(userWith("Ny")),
    json(userWith("Ny")),
  ]);
  await runCommand(scimClient, parseArguments(["set", "W0123ABCD", "Ny", "--apply"]));
  assertEquals(calls.map((call) => call.method), ["GET", "PATCH", "GET"]);
});

Deno.test("runCommand kastar om Slack inte visar nya värdet", async () => {
  const { scimClient } = client([
    json(userWith("Gammal")),
    json(userWith("Gammal")),
    json(userWith("Gammal")),
  ]);
  await assertRejects(() =>
    runCommand(scimClient, parseArguments(["set", "W0123ABCD", "Ny", "--apply"]))
  );
});

Deno.test("runCommand hoppar över när värdet redan stämmer", async () => {
  const { scimClient, calls } = client([json(userWith("IT"))]);
  await runCommand(scimClient, parseArguments(["set", "W0123ABCD", "IT", "--apply"]));
  assertEquals(calls.length, 1);
});
