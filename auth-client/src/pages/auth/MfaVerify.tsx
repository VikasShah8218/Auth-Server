import { KeyRound } from "lucide-react";
import { useState } from "react";

import { useSecurityKeySignIn, useVerifyTotp, type LoginResult } from "@/api/identity";
import { OtpInput } from "@/components/common/OtpInput";
import { AuthLayout } from "@/components/layout/AuthLayout";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError, userMessage } from "@/lib/errors";

/** The second step: a 6-digit code, or a security key. */
export default function MfaVerify({
  challenge,
  methods,
  onAuthenticated,
  onRestart,
}: {
  challenge: string;
  methods: string[];
  onAuthenticated: () => void;
  onRestart: (message?: string) => void;
}) {
  const [code, setCode] = useState("");
  const totp = useVerifyTotp();
  const securityKey = useSecurityKeySignIn();
  const hasTotp = methods.includes("totp");
  const hasKey = methods.includes("webauthn");

  function handle(result: LoginResult) {
    if (result.status === "authenticated") onAuthenticated();
  }

  function onError(error: unknown) {
    // An expired or exhausted challenge can't be retried: start again from the password.
    if (error instanceof ApiError && error.code === "mfa_challenge_expired") onRestart(userMessage(error));
    else setCode("");
  }

  function verify(value = code) {
    if (value.length !== 6 || totp.isPending) return;
    totp.mutate({ challenge, code: value }, { onSuccess: handle, onError });
  }

  function signInWithKey() {
    securityKey.mutate(challenge, {
      onSuccess: handle,
      onError,
    });
  }

  const error = totp.error ?? securityKey.error;
  const keyCancelled = error instanceof Error && error.name === "NotAllowedError";

  return (
    <AuthLayout footer="Lost your phone or security key? Ask an administrator to reset your MFA.">
      <div className="grid gap-[18px]">
        <div>
          <h1 className="text-[22px] font-bold">{hasTotp ? "Enter your code" : "Use your security key"}</h1>
          <p className="mt-1 text-[13.5px] text-fg-2">
            {hasTotp ? (
              <>
                Open your authenticator app and type the 6-digit code for <b>Auth Server</b>.
              </>
            ) : (
              "Insert or tap your security key to finish signing in."
            )}
          </p>
        </div>

        {error && !keyCancelled && <Alert tone="danger">{userMessage(error)}</Alert>}
        {keyCancelled && (
          <Alert tone="warn">The security key prompt was closed. Try again when you're ready.</Alert>
        )}

        {hasTotp && (
          <form
            className="grid gap-[18px]"
            onSubmit={(event) => {
              event.preventDefault();
              verify();
            }}
          >
            <div className="grid gap-1.5">
              <OtpInput
                value={code}
                onChange={setCode}
                onComplete={verify}
                autoFocus
                disabled={totp.isPending}
                invalid={!!totp.error}
              />
              <span className="text-xs text-muted">
                The code changes every 30 seconds. After 5 wrong codes you sign in again.
              </span>
            </div>
            <Button
              type="submit"
              variant="primary"
              block
              loading={totp.isPending}
              disabled={code.length !== 6}
            >
              Verify and continue
            </Button>
          </form>
        )}

        {hasTotp && hasKey && (
          <div className="flex items-center gap-2.5 text-xs text-muted before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line">
            or
          </div>
        )}

        {hasKey && (
          <Button
            block
            variant={hasTotp ? "secondary" : "primary"}
            loading={securityKey.isPending}
            onClick={signInWithKey}
          >
            <KeyRound />
            Use a security key
          </Button>
        )}

        <button
          type="button"
          onClick={() => onRestart()}
          className="cursor-pointer justify-self-center border-0 bg-transparent p-0 text-[13px] font-medium text-accent-strong hover:underline"
        >
          Back to password
        </button>
      </div>
    </AuthLayout>
  );
}
