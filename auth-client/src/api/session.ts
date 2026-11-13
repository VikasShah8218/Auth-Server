import { queryOptions, useMutation, useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/errors";

import { api, call, setCsrfToken, type Schemas } from "./client";
import { qk } from "./keys";

export type ConsoleSession = Schemas["ConsoleSession"];

/** The console session, or null when there is none (the 401 is an answer here, not an error). */
export const sessionQuery = queryOptions({
  queryKey: qk.session,
  queryFn: async (): Promise<ConsoleSession | null> => {
    try {
      const session = await call(api.GET("/bff/session"));
      setCsrfToken(session.csrf_token);
      return session;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setCsrfToken(null);
        return null;
      }
      throw error;
    }
  },
  staleTime: 5 * 60 * 1000,
});

/** For components inside the signed-in shell, where the session is known to exist. */
export function useSession(): ConsoleSession {
  const { data } = useQuery(sessionQuery);
  if (!data) throw new Error("useSession used outside the signed-in app");
  return data;
}

/**
 * Ends the console session and the SSO session, then shows the login page. The full page load that follows
 * drops every cached query; clearing the cache here instead would pull the session out from under the
 * still-mounted shell.
 */
export function useLogout() {
  return useMutation({
    mutationFn: () => call(api.POST("/bff/logout")),
    onSettled: () => {
      setCsrfToken(null);
      window.location.assign("/login");
    },
  });
}
