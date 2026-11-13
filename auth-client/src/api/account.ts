/** /v1/me: the signed-in user's own account. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call, postJson, type Schemas } from "./client";
import { qk } from "./keys";

export function useMe() {
  return useQuery({ queryKey: qk.me.profile, queryFn: () => call(api.GET("/v1/me")) });
}

export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["PasswordChange"]) => call(api.POST("/v1/me/password", { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.me.sessions }),
  });
}

export function useMySessions() {
  return useQuery({ queryKey: qk.me.sessions, queryFn: () => call(api.GET("/v1/me/sessions")) });
}

export function useEndMySession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      call(api.DELETE("/v1/me/sessions/{session_id}", { params: { path: { session_id: sessionId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.me.sessions }),
  });
}

export function useMyFactors() {
  return useQuery({ queryKey: qk.me.factors, queryFn: () => call(api.GET("/v1/me/mfa")) });
}

export function useStartTotp() {
  return useMutation({
    mutationFn: (password: string) => call(api.POST("/v1/me/mfa/totp", { body: { password } })),
  });
}

export function useConfirmTotp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => call(api.POST("/v1/me/mfa/totp/confirm", { body: { code } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.me.factors }),
  });
}

export function useRemoveTotp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => call(api.POST("/v1/me/mfa/totp/remove", { body: { code } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.me.factors }),
  });
}

/** Registers a security key: password step-up, browser ceremony, then the credential. */
export function useAddSecurityKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ password, name }: { password: string; name: string }) => {
      const { startRegistration } = await import("@simplewebauthn/browser");
      const optionsJSON = await postJson<Parameters<typeof startRegistration>[0]["optionsJSON"]>(
        "/v1/me/mfa/webauthn/options",
        { password },
      );
      const credential = await startRegistration({ optionsJSON });
      return postJson<null>("/v1/me/mfa/webauthn/register", { credential, name });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.me.factors }),
  });
}

export function useRemoveSecurityKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ factorId, password }: { factorId: string; password: string }) =>
      call(
        api.POST("/v1/me/mfa/webauthn/{factor_id}/remove", {
          params: { path: { factor_id: factorId } },
          body: { password },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.me.factors }),
  });
}
