/**
 * collectors.ts — En asynkron funktion per område som hämtar Slack-inställningar.
 * Fångar "mjuka" API-fel (scope saknas, feature ej tillgänglig) och rapporterar dem
 * i resultatet i stället för att krascha exporten.
 */

import { ApiError, SlackClient } from "./client.ts";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CollectorResult {
  area: string;
  file: string;
  data: unknown;
  error?: string;
  count?: number;
}

// ── Helper ────────────────────────────────────────────────────────────────────

async function safeCollect(
  area: string,
  file: string,
  fn: () => Promise<unknown>,
): Promise<CollectorResult> {
  try {
    const data = await fn();
    const count = Array.isArray(data) ? data.length : undefined;
    return { area, file, data, count };
  } catch (e) {
    if (e instanceof ApiError && e.isSoft) {
      return { area, file, data: null, error: e.code };
    }
    throw e;
  }
}

/** Kör fn per objekt i listan; fångar mjuka fel per objekt och lägger på `_error`-fält. */
async function perItem<T extends Record<string, unknown>>(
  items: T[],
  fn: (item: T) => Promise<Record<string, unknown>>,
): Promise<(T & Record<string, unknown>)[]> {
  const results: (T & Record<string, unknown>)[] = [];
  for (const item of items) {
    try {
      results.push({ ...item, ...(await fn(item)) });
    } catch (e) {
      results.push({
        ...item,
        _error: e instanceof ApiError ? e.code : String(e),
      });
    }
  }
  return results;
}

// ── Collectors ────────────────────────────────────────────────────────────────

export function collectOrgInfo(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Org-info", "01-org-info", async () => {
    const teamInfo = await client.call("team.info");
    const teamId = (teamInfo.team as Record<string, unknown>)?.id as string | undefined;
    let teamsSettings: unknown = null;
    if (teamId) {
      try {
        const r = await client.call("admin.teams.settings.info", { team_id: teamId });
        teamsSettings = r.team;
      } catch (e) {
        if (!(e instanceof ApiError && e.isSoft)) throw e;
        teamsSettings = { _error: (e as ApiError).code };
      }
    }
    return { team_info: teamInfo.team, teams_settings_info: teamsSettings };
  });
}

export function collectWorkspaces(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Workspaces", "02-workspaces", async () => {
    const teams: Record<string, unknown>[] = [];
    for await (const page of client.paginate("admin.teams.list", { limit: 100 })) {
      teams.push(...((page.teams as Record<string, unknown>[]) ?? []));
    }
    return await perItem(teams, async (team) => {
      const id = team.id as string;
      const [adminsResp, ownersResp] = await Promise.all([
        client.call("admin.teams.admins.list", { team_id: id, limit: 100 }).catch((e: ApiError) => ({
          admin_ids: null,
          _error: e.code,
        })),
        client.call("admin.teams.owners.list", { team_id: id, limit: 100 }).catch((e: ApiError) => ({
          owner_ids: null,
          _error: e.code,
        })),
      ]);
      return {
        admin_ids: (adminsResp as Record<string, unknown>).admin_ids,
        owner_ids: (ownersResp as Record<string, unknown>).owner_ids,
      };
    });
  });
}

export function collectApps(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Appar", "03-apps", async () => {
    const approved: unknown[] = [];
    for await (const page of client.paginate("admin.apps.approved.list", { limit: 200 })) {
      approved.push(...((page.approved_apps as unknown[]) ?? []));
    }
    const restricted: unknown[] = [];
    for await (const page of client.paginate("admin.apps.restricted.list", { limit: 200 })) {
      restricted.push(...((page.restricted_apps as unknown[]) ?? []));
    }
    return { approved, restricted };
  });
}

export function collectConversations(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Kanaler", "04-conversations", async () => {
    // Hämta alla kanaler med conversations.list (kräver channels:read + groups:read).
    // Faller tillbaka på admin.conversations.search vid scope-fel.
    const channels: Record<string, unknown>[] = [];
    try {
      for await (
        const page of client.paginate("conversations.list", {
          types: "public_channel,private_channel",
          limit: 200,
          exclude_archived: 0,
        })
      ) {
        channels.push(...((page.channels as Record<string, unknown>[]) ?? []));
      }
    } catch (e) {
      if (!(e instanceof ApiError && e.isSoft)) throw e;
      // Fallback: admin.conversations.search med tom query
      try {
        for await (
          const page of client.paginate("admin.conversations.search", {
            query: "",
            limit: 200,
          })
        ) {
          channels.push(...((page.conversations as Record<string, unknown>[]) ?? []));
        }
      } catch (e2) {
        if (!(e2 instanceof ApiError && e2.isSoft)) throw e2;
        return { channels: [], _error: `channel_list: ${(e2 as ApiError).code}` };
      }
    }

    // Hämta per-kanal prefs och retention för varje kanal
    return await perItem(channels, async (ch) => {
      const id = ch.id as string;
      const [prefsResp, retentionResp] = await Promise.all([
        client
          .call("admin.conversations.getConversationPrefs", { channel_id: id })
          .then((r) => r.prefs)
          .catch((e: ApiError) => ({ _error: e.code })),
        client
          .call("admin.conversations.getCustomRetention", { channel_id: id })
          .then((r) => ({ is_policy_enabled: r.is_policy_enabled, duration_days: r.duration_days }))
          .catch((e: ApiError) => ({ _error: e.code })),
      ]);
      return { prefs: prefsResp, retention: retentionResp };
    });
  });
}

export function collectBarriers(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Informationsbarriärer", "05-barriers", async () => {
    const barriers: unknown[] = [];
    for await (const page of client.paginate("admin.barriers.list", { limit: 200 })) {
      barriers.push(...((page.barriers as unknown[]) ?? []));
    }
    return barriers;
  });
}

export function collectEmoji(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Custom emoji", "06-emoji", async () => {
    const all: Record<string, unknown> = {};
    for await (const page of client.paginate("admin.emoji.list", { limit: 200 })) {
      Object.assign(all, (page.emoji as Record<string, unknown>) ?? {});
    }
    return all;
  });
}

export function collectAuthPolicy(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Auth-policy (email_password)", "07-auth-policy", async () => {
    const entities: unknown[] = [];
    for await (
      const page of client.paginate("admin.auth.policy.getEntities", {
        policy_name: "email_password",
        limit: 200,
      })
    ) {
      entities.push(...((page.entities as unknown[]) ?? []));
    }
    return { policy_name: "email_password", entities };
  });
}

export function collectUsers(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Org-användare", "08-users", async () => {
    const users: unknown[] = [];
    for await (const page of client.paginate("admin.users.list", { limit: 200 })) {
      users.push(...((page.users as unknown[]) ?? []));
    }
    return users;
  });
}

export function collectSessions(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Aktiva sessioner", "09-sessions", async () => {
    const sessions: unknown[] = [];
    for await (const page of client.paginate("admin.users.session.list", { limit: 200 })) {
      sessions.push(...((page.active_sessions as unknown[]) ?? []));
    }
    return sessions;
  });
}

export function collectProfileFields(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Profilfältsdefinitioner", "10-profile-fields", async () => {
    const r = await client.call("team.profile.get");
    return r.profile;
  });
}

export function collectWorkspacePrefs(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Workspace-inställningar", "11-workspace-prefs", async () => {
    const r = await client.call("team.preferences.list");
    // Ta bort ok-flaggan — keep bara prefs-nycklarna
    const { ok: _ok, ...prefs } = r;
    return prefs;
  });
}

export function collectScimUsers(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("SCIM-användare", "12-scim-users", async () => {
    const users: unknown[] = [];
    for await (const page of client.scimPaginate("Users")) {
      users.push(...((page.Resources as unknown[]) ?? []));
    }
    return users;
  });
}

export function collectScimGroups(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("SCIM-grupper", "13-scim-groups", async () => {
    const groups: unknown[] = [];
    for await (const page of client.scimPaginate("Groups")) {
      groups.push(...((page.Resources as unknown[]) ?? []));
    }
    return groups;
  });
}

export function collectScimConfig(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("SCIM ServiceProviderConfig", "14-scim-config", async () => {
    return await client.scimGet("ServiceProviderConfig");
  });
}

export function collectAuditLogs(client: SlackClient): Promise<CollectorResult> {
  return safeCollect("Audit log (senaste 30 dagar)", "15-audit-recent", async () => {
    const oldest = Math.floor(Date.now() / 1000) - 30 * 24 * 60 * 60;
    const entries: unknown[] = [];
    for await (const page of client.auditPaginate({ oldest, limit: 1000 })) {
      entries.push(...((page.entries as unknown[]) ?? []));
      if (entries.length >= 5000) break; // rimlig gräns för ett testorg
    }
    return entries;
  });
}

// ── collectAll ────────────────────────────────────────────────────────────────

export async function collectAll(client: SlackClient): Promise<CollectorResult[]> {
  const collectors = [
    collectOrgInfo,
    collectWorkspaces,
    collectApps,
    collectConversations,
    collectBarriers,
    collectEmoji,
    collectAuthPolicy,
    collectUsers,
    collectSessions,
    collectProfileFields,
    collectWorkspacePrefs,
    collectScimUsers,
    collectScimGroups,
    collectScimConfig,
    collectAuditLogs,
  ];
  const results: CollectorResult[] = [];
  for (const collector of collectors) {
    results.push(await collector(client));
  }
  return results;
}
