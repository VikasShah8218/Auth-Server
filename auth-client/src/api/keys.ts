/** Query keys, in one place so a mutation invalidates exactly what it changed. */

export type UsersFilters = { q?: string; status?: string; app?: string; offset: number };
export type AuditFilters = { actor?: string; action?: string; app?: string; offset: number };

export const qk = {
  session: ["session"] as const,
  stats: ["stats"] as const,
  me: {
    all: ["me"] as const,
    profile: ["me", "profile"] as const,
    sessions: ["me", "sessions"] as const,
    factors: ["me", "factors"] as const,
  },
  users: {
    all: ["users"] as const,
    list: (filters: UsersFilters) => ["users", "list", filters] as const,
    detail: (id: string) => ["users", "detail", id] as const,
    sessions: (id: string) => ["users", "detail", id, "sessions"] as const,
    factors: (id: string) => ["users", "detail", id, "factors"] as const,
  },
  apps: {
    all: ["apps"] as const,
    list: (offset: number) => ["apps", "list", offset] as const,
    options: ["apps", "options"] as const,
    detail: (key: string) => ["apps", "detail", key] as const,
    permissions: (key: string, retired: boolean) => ["apps", "detail", key, "permissions", retired] as const,
    roles: (key: string) => ["apps", "detail", key, "roles"] as const,
    role: (key: string, id: number) => ["apps", "detail", key, "roles", id] as const,
    members: (key: string) => ["apps", "detail", key, "members"] as const,
  },
  clients: {
    all: ["clients"] as const,
    list: (app?: string) => ["clients", "list", app ?? null] as const,
    detail: (id: string) => ["clients", "detail", id] as const,
  },
  signingKeys: ["signing-keys"] as const,
  downstream: ["downstream"] as const,
  audit: {
    all: ["audit"] as const,
    list: (filters: AuditFilters) => ["audit", "list", filters] as const,
  },
};
