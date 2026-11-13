/**
 * Where the login page may send the browser after a successful sign-in.
 *
 * Only a same-origin `/oauth/authorize?...` path is accepted. Anything else (an absolute URL, `//host`, a
 * backslash trick, `javascript:`, any other path) would turn the login page into an open redirect, so it
 * falls back to the console's own sign-in, which ends at the dashboard.
 */
export const DEFAULT_RETURN_TO = "/bff/login";

export function safeReturnTo(
  value: string | null | undefined,
  origin: string = window.location.origin,
): string {
  if (!value || typeof value !== "string") return DEFAULT_RETURN_TO;
  if (!value.startsWith("/oauth/authorize?") && value !== "/oauth/authorize") return DEFAULT_RETURN_TO;
  if (/[\\\s]/.test(value) || value.startsWith("//")) return DEFAULT_RETURN_TO;
  try {
    const url = new URL(value, origin);
    if (url.origin !== origin || url.pathname !== "/oauth/authorize") return DEFAULT_RETURN_TO;
    return url.pathname + url.search;
  } catch {
    return DEFAULT_RETURN_TO;
  }
}
