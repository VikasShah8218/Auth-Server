/**
 * The one way the app talks to the Auth Server.
 *
 * Same origin, cookie session (backend-for-frontend): no token ever reaches this code. Writes carry the CSRF
 * token from GET /bff/session. A 401 on the console's API sends the browser through sign-in again.
 */
import createClient, { type Middleware } from "openapi-fetch";

import { toApiError } from "@/lib/errors";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
// Only these answer 401 because the console session ended. Sign-in endpoints answer 401 for a wrong password.
const SESSION_PATHS = /^\/v1\/(admin|me)(\/|$)/;

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Start the console sign-in: the server redirects to /oauth/authorize, then to /login if needed. */
export function startConsoleLogin(): void {
  window.location.assign("/bff/login");
}

const middleware: Middleware = {
  onRequest({ request }) {
    if (!SAFE_METHODS.has(request.method) && csrfToken) request.headers.set("x-csrf-token", csrfToken);
    return request;
  },
  onResponse({ request, response }) {
    if (response.status === 401 && SESSION_PATHS.test(new URL(request.url).pathname)) {
      setCsrfToken(null);
      startConsoleLogin();
    }
    return response;
  },
};

api.use(middleware);

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Await an openapi-fetch call: the data on success, an ApiError otherwise. */
export async function call<T>(request: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await request;
  if (!response.ok || error !== undefined) throw toApiError(response, error ?? null);
  return data as T;
}

/** Endpoints the schema doesn't type (WebAuthn options): plain JSON, same rules. */
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (csrfToken) headers["x-csrf-token"] = csrfToken;
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(body),
  });
  const data = response.headers.get("content-type")?.includes("json") ? await response.json() : null;
  if (!response.ok) throw toApiError(response, data);
  return data as T;
}
