/**
 * client.ts — HTTP-klient för Slack Web API, Audit Logs API och SCIM v2.
 * Injektabelt fetch och sleep för testbarhet. Hanterar 429 / retry-after.
 */

export const WEB_API_BASE = "https://slack.com/api";
export const AUDIT_API_BASE = "https://api.slack.com/audit/v1";
export const SCIM_API_BASE = "https://api.slack.com/scim/v2";
export const MAX_RETRIES = 3;
const DEFAULT_RETRY_MS = 5_000;

/** Felkoder som betyder "feature/scope saknas" — kollektor rapporterar, kraschar inte. */
export const SOFT_ERROR_CODES = new Set([
  "missing_scope",
  "not_in_enterprise",
  "feature_not_enabled",
  "enterprise_is_restricted",
  "unsupported_team_type",
  "policy_not_found",
  "ekm_access_denied",
  "no_permission",
  "method_not_supported_for_channel_type",
  "channel_not_found",
]);

export type FetchFn = typeof fetch;

export interface ClientOptions {
  token: string;
  fetchFn?: FetchFn;
  sleepFn?: (ms: number) => Promise<void>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly httpStatus = 0,
  ) {
    super(message);
    this.name = "ApiError";
  }
  get isSoft(): boolean {
    return SOFT_ERROR_CODES.has(this.code);
  }
}

export class SlackClient {
  readonly #token: string;
  readonly #fetch: FetchFn;
  readonly #sleep: (ms: number) => Promise<void>;

  constructor({ token, fetchFn, sleepFn }: ClientOptions) {
    this.#token = token;
    this.#fetch = fetchFn ?? fetch;
    this.#sleep = sleepFn ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  }

  async call(
    method: string,
    params: Record<string, string | number> = {},
  ): Promise<Record<string, unknown>> {
    const form = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) form.set(k, String(v));
    const response = await this.#retryRequest(() =>
      this.#fetch(`${WEB_API_BASE}/${method}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${this.#token}`,
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: form.toString(),
      })
    );
    const json = (await response.json()) as Record<string, unknown>;
    if (!json.ok) {
      const code = String(json.error ?? "unknown_error");
      throw new ApiError(`${method}: ${code}`, code, response.status);
    }
    return json;
  }

  async *paginate(
    method: string,
    params: Record<string, string | number> = {},
  ): AsyncGenerator<Record<string, unknown>> {
    let cursor: string | undefined;
    do {
      const page = await this.call(method, cursor ? { ...params, cursor } : params);
      yield page;
      cursor = nextCursor(page);
    } while (cursor);
  }

  async *auditPaginate(
    params: Record<string, string | number> = {},
  ): AsyncGenerator<Record<string, unknown>> {
    let cursor: string | undefined;
    do {
      const page = await this.#get(
        `${AUDIT_API_BASE}/logs`,
        cursor ? { ...params, cursor } : params,
        "audit",
      );
      yield page;
      cursor = nextCursor(page);
    } while (cursor);
  }

  async *scimPaginate(
    resource: string,
    countPerPage = 200,
  ): AsyncGenerator<Record<string, unknown>> {
    let startIndex = 1;
    while (true) {
      const page = await this.#get(
        `${SCIM_API_BASE}/${resource}`,
        { startIndex, count: countPerPage },
        "scim",
      );
      yield page;
      const returned = (page.Resources as unknown[] | undefined)?.length ?? 0;
      if (returned < countPerPage) break;
      startIndex += returned;
    }
  }

  async scimGet(path: string): Promise<Record<string, unknown>> {
    return await this.#get(`${SCIM_API_BASE}/${path}`, {}, "scim");
  }

  async #get(
    url: string,
    params: Record<string, string | number>,
    context: string,
  ): Promise<Record<string, unknown>> {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) qs.set(k, String(v));
    const full = Object.keys(params).length ? `${url}?${qs}` : url;
    const response = await this.#retryRequest(() =>
      this.#fetch(full, {
        headers: { Authorization: `Bearer ${this.#token}`, Accept: "application/json" },
      })
    );
    if (!response.ok) {
      const text = await response.text();
      const code = extractCode(text);
      throw new ApiError(`${context} HTTP ${response.status}`, code, response.status);
    }
    return (await response.json()) as Record<string, unknown>;
  }

  async #retryRequest(makeRequest: () => Promise<Response>): Promise<Response> {
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      const response = await makeRequest();
      if (response.status !== 429 || attempt >= MAX_RETRIES) return response;
      const wait = (Number(response.headers.get("retry-after")) || 5) * 1000;
      await response.body?.cancel();
      await this.#sleep(wait ?? DEFAULT_RETRY_MS);
    }
    throw new ApiError("Too many retries", "rate_limited", 429);
  }
}

function nextCursor(page: Record<string, unknown>): string | undefined {
  const meta = page.response_metadata as Record<string, unknown> | undefined;
  const c = meta?.next_cursor;
  return typeof c === "string" && c.length > 0 ? c : undefined;
}

function extractCode(text: string): string {
  try {
    const j = JSON.parse(text) as Record<string, unknown>;
    return String(j?.error ?? j?.errors ?? "http_error");
  } catch {
    return "http_error";
  }
}
