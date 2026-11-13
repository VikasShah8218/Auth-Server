import { getRouteApi } from "@tanstack/react-router";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { useLogin, type LoginResult } from "@/api/identity";
import { FormField } from "@/components/common/FormField";
import { AuthLayout } from "@/components/layout/AuthLayout";
import { BrandMark } from "@/components/layout/BrandMark";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { userMessage } from "@/lib/errors";
import { safeReturnTo } from "@/lib/returnTo";

import MfaVerify from "./MfaVerify";

// The login page is the first thing every app's users load, so it stays small: two required fields need
// no form or schema library.

const route = getRouteApi("/login");

/** Errors the console's own sign-in can send back here as ?error=. */
const CALLBACK_ERRORS: Record<string, string> = {
  invalid_state: "The sign-in took too long or was opened in another browser. Sign in again.",
  invalid_code: "The sign-in couldn't be completed. Sign in again.",
  access_denied: "Your account has no access to this application. Ask an administrator for access.",
  login_required: "Sign in to continue.",
};

export default function Login() {
  const { return_to: returnTo, error: callbackError } = route.useSearch();
  const login = useLogin();
  const [mfa, setMfa] = useState<{ challenge: string; methods: string[] } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [missing, setMissing] = useState<{ username?: string; password?: string }>({});
  const passwordInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = "Sign in · Auth Server";
  }, []);

  function finish() {
    window.location.assign(safeReturnTo(returnTo));
  }

  function onResult(result: LoginResult) {
    if (result.status === "authenticated") finish();
    else setMfa({ challenge: result.challenge ?? "", methods: result.methods ?? [] });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const errors = {
      username: username.trim() ? undefined : "Enter your username.",
      password: password ? undefined : "Enter your password.",
    };
    setMissing(errors);
    if (errors.username || errors.password) return;
    setNotice(null);
    login.mutate(
      { username: username.trim(), password },
      { onSuccess: onResult, onError: () => setPassword("") },
    );
  }

  if (mfa) {
    return (
      <MfaVerify
        challenge={mfa.challenge}
        methods={mfa.methods}
        onAuthenticated={finish}
        onRestart={(message) => {
          setMfa(null);
          setNotice(message ?? null);
          setPassword("");
          window.setTimeout(() => passwordInput.current?.focus(), 0);
        }}
      />
    );
  }

  const error = login.error
    ? userMessage(login.error)
    : (notice ?? (callbackError ? CALLBACK_ERRORS[callbackError] : null));

  return (
    <AuthLayout footer="Forgot your password? Ask an administrator to reset it.">
      <form onSubmit={submit} noValidate className="grid gap-[18px]">
        <div className="flex items-center gap-2.5">
          <BrandMark />
          <h1 className="text-[22px] font-bold">Sign in</h1>
        </div>
        <p className="-mt-2 text-fg-2">One sign-in for ANPR, NVR and every connected app.</p>

        {error && <Alert tone="danger">{error}</Alert>}

        <FormField label="Username" error={missing.username}>
          <Input
            name="username"
            autoComplete="username"
            autoFocus
            autoCapitalize="none"
            spellCheck={false}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </FormField>
        <FormField label="Password" error={missing.password}>
          <Input
            ref={passwordInput}
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </FormField>

        <Button type="submit" variant="primary" block loading={login.isPending}>
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
