/**
 * department.ts
 * Läser, sätter och tar bort SCIM-fältet Department för en Slack-användare.
 *
 * Fungerar mot alla Slack-organisationer (Business+ / Enterprise) som har
 * SCIM aktiverat. Kräver en användartoken (xoxp-) med scopen `admin`,
 * installerad av en Owner/Org Owner. Modulen är fri från CLI-logik och tar
 * en valfri fetch-funktion så att den kan återanvändas i ett Workflow
 * Builder-steg (Deno Slack SDK) och testas utan nätverk.
 */

// ── Configuration ─────────────────────────────────────────────────────────────

export const SCIM_BASE_URL = "https://api.slack.com/scim";
export const WEB_API_BASE_URL = "https://slack.com/api";
export const ENTERPRISE_SCHEMA =
  "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User";
export const PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp";
export const DEPARTMENT_PATH = `${ENTERPRISE_SCHEMA}:department`;

/** Konservativ gräns; Slack dokumenterar ingen exakt maxlängd. */
export const MAX_DEPARTMENT_LENGTH = 256;
export const MAX_RETRIES = 3;
export const DEFAULT_RETRY_SECONDS = 5;

const SLACK_USER_ID_PATTERN = /^[UW][A-Z0-9]{6,}$/;
const EMAIL_PATTERN = /^[^\s@"]+@[^\s@"]+\.[^\s@"]+$/;
// deno-lint-ignore no-control-regex
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f]/;

// ── Types ─────────────────────────────────────────────────────────────────────

export type FetchFunction = typeof fetch;

export interface ScimClientOptions {
  token: string;
  fetchFunction?: FetchFunction;
  sleepFunction?: (milliseconds: number) => Promise<void>;
}

export class ScimError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: string,
  ) {
    super(message);
    this.name = "ScimError";
  }
}

// ── Validation ────────────────────────────────────────────────────────────────

export function validateDepartment(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length === 0) {
    throw new Error("Department får inte vara tomt; använd delete för att ta bort.");
  }
  if (trimmed.length > MAX_DEPARTMENT_LENGTH) {
    throw new Error(`Department är längre än ${MAX_DEPARTMENT_LENGTH} tecken.`);
  }
  if (CONTROL_CHARACTER_PATTERN.test(trimmed)) {
    throw new Error("Department innehåller kontrolltecken.");
  }
  return trimmed;
}

export function isSlackUserId(identifier: string): boolean {
  return SLACK_USER_ID_PATTERN.test(identifier);
}

export function isEmail(identifier: string): boolean {
  return EMAIL_PATTERN.test(identifier);
}

// ── Client ────────────────────────────────────────────────────────────────────

export class ScimDepartmentClient {
  readonly #token: string;
  readonly #fetch: FetchFunction;
  readonly #sleep: (milliseconds: number) => Promise<void>;

  constructor(options: ScimClientOptions) {
    if (!/^(xoxe\.)?xoxp-/.test(options.token)) {
      throw new Error("SCIM kräver en användartoken som börjar med xoxp-.");
    }
    this.#token = options.token;
    this.#fetch = options.fetchFunction ?? fetch;
    this.#sleep = options.sleepFunction ??
      ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
  }

  /**
   * Slack-ID returneras direkt. E-post slås upp med users.lookupByEmail
   * (kräver users:read + users:read.email), eftersom SCIM v1 inte fungerar
   * på Enterprise Grid och v2 saknar dokumenterat e-postfilter.
   */
  async resolveUserId(identifier: string): Promise<string> {
    const cleaned = identifier.trim();
    if (isSlackUserId(cleaned)) return cleaned;
    if (!isEmail(cleaned)) {
      throw new Error(`Varken Slack-ID eller e-postadress: ${cleaned}`);
    }
    const url = `${WEB_API_BASE_URL}/users.lookupByEmail?email=${encodeURIComponent(cleaned)}`;
    const response = await this.#fetch(url, {
      headers: { "Authorization": `Bearer ${this.#token}` },
    });
    const body = await response.json();
    if (!body?.ok || !body.user?.id) {
      const code = String(body?.error ?? response.status);
      const status = code === "users_not_found" ? 404 : 400;
      throw new ScimError(`users.lookupByEmail misslyckades för ${cleaned}`, status, code);
    }
    return body.user.id;
  }

  async getDepartment(userId: string): Promise<string | null> {
    const body = await this.#request("GET", `/v2/Users/${encodeURIComponent(userId)}`);
    const department = body?.[ENTERPRISE_SCHEMA]?.department;
    return typeof department === "string" && department.length > 0 ? department : null;
  }

  async setDepartment(userId: string, value: string): Promise<void> {
    const department = validateDepartment(value);
    await this.#patch(userId, { op: "add", path: DEPARTMENT_PATH, value: department });
  }

  async deleteDepartment(userId: string): Promise<void> {
    await this.#patch(userId, { op: "remove", path: DEPARTMENT_PATH });
  }

  async #patch(userId: string, operation: Record<string, unknown>): Promise<void> {
    await this.#request("PATCH", `/v2/Users/${encodeURIComponent(userId)}`, {
      schemas: [PATCH_SCHEMA],
      Operations: [operation],
    });
  }

  // deno-lint-ignore no-explicit-any
  async #request(method: string, path: string, payload?: unknown): Promise<any> {
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      const response = await this.#fetch(`${SCIM_BASE_URL}${path}`, {
        method,
        headers: {
          "Authorization": `Bearer ${this.#token}`,
          "Content-Type": "application/json; charset=utf-8",
          "Accept": "application/json",
        },
        body: payload === undefined ? undefined : JSON.stringify(payload),
      });
      if (response.status === 429 && attempt < MAX_RETRIES) {
        await response.body?.cancel();
        const retrySeconds = Number(response.headers.get("retry-after")) ||
          DEFAULT_RETRY_SECONDS;
        await this.#sleep(retrySeconds * 1000);
        continue;
      }
      const text = await response.text();
      if (!response.ok) {
        throw new ScimError(
          `SCIM ${method} ${path} misslyckades (${response.status})`,
          response.status,
          extractErrorDetail(text),
        );
      }
      return text.length > 0 ? JSON.parse(text) : null;
    }
    throw new ScimError(`SCIM ${method} ${path}: för många försök`, 429, "too_many_requests");
  }
}

function extractErrorDetail(text: string): string {
  try {
    const parsed = JSON.parse(text);
    return parsed?.Errors?.description ?? parsed?.detail ?? parsed?.error ?? text;
  } catch {
    return text.slice(0, 300);
  }
}
