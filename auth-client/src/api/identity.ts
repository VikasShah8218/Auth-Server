/** Sign-in endpoints (public). Used by the hosted login page, which also serves every other app. */
import { useMutation } from "@tanstack/react-query";

import { api, call, postJson, type Schemas } from "./client";

export type LoginResult = Schemas["LoginResponse"];

export function useLogin() {
  return useMutation({
    mutationFn: (body: Schemas["LoginRequest"]) => call(api.POST("/v1/identity/login", { body })),
  });
}

export function useVerifyTotp() {
  return useMutation({
    mutationFn: (body: Schemas["MfaVerifyRequest"]) => call(api.POST("/v1/identity/mfa/verify", { body })),
  });
}

/** Security key sign-in: options for navigator.credentials.get(), then the assertion back. */
export function useSecurityKeySignIn() {
  return useMutation({
    mutationFn: async (challenge: string): Promise<LoginResult> => {
      const { startAuthentication } = await import("@simplewebauthn/browser");
      const optionsJSON = await postJson<Parameters<typeof startAuthentication>[0]["optionsJSON"]>(
        "/v1/identity/webauthn/options",
        { challenge },
      );
      const credential = await startAuthentication({ optionsJSON });
      return postJson<LoginResult>("/v1/identity/webauthn/verify", { challenge, credential });
    },
  });
}
