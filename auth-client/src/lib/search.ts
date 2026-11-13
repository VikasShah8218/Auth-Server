/** URL search params for each page. Filters and paging live in the URL, so they survive reloads and links. */

type Raw = Record<string, unknown>;

const text = (value: unknown, max = 200): string | undefined =>
  typeof value === "string" && value.trim() ? value.trim().slice(0, max) : undefined;

const offset = (value: unknown): number | undefined => {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : undefined;
};

const oneOf = <T extends string>(value: unknown, options: readonly T[]): T | undefined =>
  options.includes(value as T) ? (value as T) : undefined;

export type LoginSearch = { return_to?: string; error?: string };
// return_to carries a whole /oauth/authorize URL (PKCE challenge, state, nonce...): it must never be cut.
// Over 4,000 characters it's dropped entirely rather than truncated, and safeReturnTo() checks what's left.
export const validateLoginSearch = (s: Raw): LoginSearch => ({
  return_to: typeof s.return_to === "string" && s.return_to.length <= 4000 ? s.return_to : undefined,
  error: text(s.error),
});

export type TabSearch = { tab?: string };
export const validateTabSearch = (s: Raw): TabSearch => ({ tab: text(s.tab) });

export type PageSearch = { offset?: number };
export const validatePageSearch = (s: Raw): PageSearch => ({ offset: offset(s.offset) });

export const USER_STATUSES = ["active", "disabled"] as const;
export type UsersSearch = {
  q?: string;
  status?: (typeof USER_STATUSES)[number];
  app?: string;
  offset?: number;
  /** Opens the "New user" dialog (from the dashboard's button). */
  create?: boolean;
};
export const validateUsersSearch = (s: Raw): UsersSearch => ({
  q: text(s.q),
  status: oneOf(s.status, USER_STATUSES),
  app: text(s.app)?.toUpperCase(),
  offset: offset(s.offset),
  create: s.create === true || s.create === "true" ? true : undefined,
});

export type ClientsSearch = { app?: string };
export const validateClientsSearch = (s: Raw): ClientsSearch => ({ app: text(s.app)?.toUpperCase() });

export type AuditSearch = { actor?: string; action?: string; app?: string; offset?: number };
export const validateAuditSearch = (s: Raw): AuditSearch => ({
  actor: text(s.actor),
  action: text(s.action),
  app: text(s.app)?.toUpperCase(),
  offset: offset(s.offset),
});
