import { KeyRound, Plus, ShieldCheck, Smartphone, Trash2 } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import {
  useAddSecurityKey,
  useConfirmTotp,
  useMyFactors,
  useRemoveSecurityKey,
  useRemoveTotp,
  useStartTotp,
} from "@/api/account";
import type { Schemas } from "@/api/client";
import { CopyButton } from "@/components/common/CopyButton";
import { FactorRow } from "@/components/common/FactorRow";
import { FormField } from "@/components/common/FormField";
import { ListRow, Tile } from "@/components/common/ListRow";
import { OtpInput } from "@/components/common/OtpInput";
import { ErrorState } from "@/components/common/States";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Dialog, DialogBody, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { userMessage } from "@/lib/errors";

type Factor = Schemas["FactorOut"];

/** Password, then QR code, then the first code. The factor protects nothing until that code confirms it. */
function TotpSetupDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const start = useStartTotp();
  const confirm = useConfirmTotp();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");

  useEffect(() => {
    if (!open) {
      setPassword("");
      setCode("");
      start.reset();
      confirm.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset on close
  }, [open]);

  const enrolment = start.data;

  function submitPassword(event: FormEvent) {
    event.preventDefault();
    if (password) start.mutate(password);
  }

  function submitCode(value = code) {
    if (value.length !== 6) return;
    confirm.mutate(value, {
      onSuccess: () => {
        toast.success("Authenticator app turned on", {
          description: "You'll be asked for a code when you sign in.",
        });
        onOpenChange(false);
      },
      onError: () => setCode(""),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {!enrolment ? (
          <form onSubmit={submitPassword}>
            <DialogBody
              icon={<Smartphone />}
              tone="accent"
              title="Set up an authenticator app"
              description="Confirm your password to continue. You'll need an app such as Google Authenticator, Microsoft Authenticator or Authy."
            >
              {start.error && <Alert tone="danger">{userMessage(start.error)}</Alert>}
              <FormField label="Current password">
                <Input
                  type="password"
                  autoFocus
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </FormField>
            </DialogBody>
            <DialogFooter>
              <DialogClose asChild>
                <Button>Cancel</Button>
              </DialogClose>
              <Button type="submit" variant="primary" loading={start.isPending} disabled={!password}>
                Continue
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              submitCode();
            }}
          >
            <DialogBody
              icon={<Smartphone />}
              tone="accent"
              title="Scan the QR code"
              description="Scan it with your authenticator app, then type the 6-digit code it shows."
            >
              <div className="mx-auto rounded-control bg-white p-3">
                <QRCodeSVG
                  value={enrolment.otpauth_uri}
                  size={176}
                  marginSize={0}
                  title="Authenticator setup QR code"
                />
              </div>
              <div className="grid gap-1">
                <span className="text-xs text-muted">Can't scan? Enter this key in the app instead:</span>
                <div className="flex items-center gap-1 rounded-control border border-line bg-surface-2 py-1 pr-1 pl-3">
                  <code className="min-w-0 flex-1 font-mono text-[13px] tracking-wider break-all">
                    {enrolment.secret}
                  </code>
                  <CopyButton value={enrolment.secret} label="Copy setup key" />
                </div>
              </div>
              {confirm.error && <Alert tone="danger">{userMessage(confirm.error)}</Alert>}
              <OtpInput
                value={code}
                onChange={setCode}
                onComplete={submitCode}
                disabled={confirm.isPending}
                invalid={!!confirm.error}
              />
            </DialogBody>
            <DialogFooter>
              <DialogClose asChild>
                <Button>Cancel</Button>
              </DialogClose>
              <Button
                type="submit"
                variant="primary"
                loading={confirm.isPending}
                disabled={code.length !== 6}
              >
                Turn on
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function RemoveTotpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const remove = useRemoveTotp();
  const [code, setCode] = useState("");
  useEffect(() => {
    if (!open) {
      setCode("");
      remove.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset on close
  }, [open]);

  function submit(value = code) {
    if (value.length !== 6) return;
    remove.mutate(value, {
      onSuccess: () => {
        toast.success("Authenticator app removed");
        onOpenChange(false);
      },
      onError: () => setCode(""),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogBody
          icon={<Trash2 />}
          tone="danger"
          title="Remove the authenticator app?"
          description="Type a current code from the app to confirm it's you."
        >
          {remove.error && <Alert tone="danger">{userMessage(remove.error)}</Alert>}
          <OtpInput
            value={code}
            onChange={setCode}
            onComplete={submit}
            autoFocus
            disabled={remove.isPending}
            invalid={!!remove.error}
          />
        </DialogBody>
        <DialogFooter>
          <DialogClose asChild>
            <Button>Cancel</Button>
          </DialogClose>
          <Button
            variant="danger"
            loading={remove.isPending}
            disabled={code.length !== 6}
            onClick={() => submit()}
          >
            Remove app
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Adding or removing a security key: the password first, then (for adding) the browser's prompt. */
function SecurityKeyDialog({
  open,
  onOpenChange,
  removing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  removing?: Factor;
}) {
  const add = useAddSecurityKey();
  const remove = useRemoveSecurityKey();
  const mutation = removing ? remove : add;
  const [password, setPassword] = useState("");
  const [name, setName] = useState("Security key");

  useEffect(() => {
    if (!open) {
      setPassword("");
      setName("Security key");
      add.reset();
      remove.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset on close
  }, [open]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const done = (message: string) => () => {
      toast.success(message);
      onOpenChange(false);
    };
    if (removing)
      remove.mutate({ factorId: removing.id, password }, { onSuccess: done("Security key removed") });
    else
      add.mutate(
        { password, name: name.trim() || "Security key" },
        { onSuccess: done("Security key added") },
      );
  }

  const cancelled = mutation.error instanceof Error && mutation.error.name === "NotAllowedError";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogBody
            icon={removing ? <Trash2 /> : <KeyRound />}
            tone={removing ? "danger" : "accent"}
            title={removing ? `Remove ${removing.name ?? "this security key"}?` : "Add a security key"}
            description={
              removing
                ? "Confirm your password. You can't sign in with this key afterwards."
                : "Confirm your password, then follow your browser's prompt to touch or insert the key."
            }
          >
            {mutation.error && !cancelled && <Alert tone="danger">{userMessage(mutation.error)}</Alert>}
            {cancelled && (
              <Alert tone="warn">The security key prompt was closed. Try again when you're ready.</Alert>
            )}
            {!removing && (
              <FormField label="Name" help="So you can tell your keys apart, e.g. YubiKey 5C.">
                <Input value={name} maxLength={64} onChange={(e) => setName(e.target.value)} />
              </FormField>
            )}
            <FormField label="Current password">
              <Input
                type="password"
                autoFocus
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </FormField>
          </DialogBody>
          <DialogFooter>
            <DialogClose asChild>
              <Button>Cancel</Button>
            </DialogClose>
            <Button
              type="submit"
              variant={removing ? "danger" : "primary"}
              loading={mutation.isPending}
              disabled={!password}
            >
              {removing ? "Remove key" : "Add key"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function MfaSettings() {
  const factors = useMyFactors();
  const [dialog, setDialog] = useState<"totp-setup" | "totp-remove" | "key-add" | null>(null);
  const [removingKey, setRemovingKey] = useState<Factor | null>(null);

  const totp = factors.data?.find((f) => f.type === "totp");
  const keys = factors.data?.filter((f) => f.type === "webauthn") ?? [];
  const on = (factors.data?.length ?? 0) > 0;
  const webauthnSupported = typeof window !== "undefined" && "PublicKeyCredential" in window;

  return (
    <Card>
      <CardHeader
        title="Two-step sign-in"
        description={
          on
            ? "On: you're asked for a second step after your password."
            : "Off: add a second step to protect your account."
        }
        actions={on ? <ShieldCheck className="size-5 text-ok" aria-label="On" /> : undefined}
      />
      {factors.isError ? (
        <ErrorState error={factors.error} onRetry={() => factors.refetch()} />
      ) : factors.isPending ? (
        <div className="grid gap-3 p-[18px]">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : (
        <div>
          {totp ? (
            <FactorRow
              factor={totp}
              action={
                <Button variant="danger-ghost" size="sm" onClick={() => setDialog("totp-remove")}>
                  Remove
                </Button>
              }
            />
          ) : (
            <ListRow
              leading={
                <Tile>
                  <Smartphone />
                </Tile>
              }
              title="Authenticator app"
              meta="6-digit codes from an app on your phone"
              action={
                <Button size="sm" onClick={() => setDialog("totp-setup")}>
                  Set up
                </Button>
              }
            />
          )}
          {keys.map((key) => (
            <FactorRow
              key={key.id}
              factor={key}
              action={
                <Button variant="danger-ghost" size="sm" onClick={() => setRemovingKey(key)}>
                  Remove
                </Button>
              }
            />
          ))}
          <ListRow
            leading={
              <Tile>
                <KeyRound />
              </Tile>
            }
            title={keys.length ? "Add another security key" : "Security key"}
            meta={
              webauthnSupported
                ? "A USB or NFC key, or your device's built-in passkey"
                : "This browser doesn't support security keys."
            }
            action={
              <Button size="sm" disabled={!webauthnSupported} onClick={() => setDialog("key-add")}>
                <Plus />
                Add
              </Button>
            }
          />
        </div>
      )}

      <TotpSetupDialog open={dialog === "totp-setup"} onOpenChange={(open) => !open && setDialog(null)} />
      <RemoveTotpDialog open={dialog === "totp-remove"} onOpenChange={(open) => !open && setDialog(null)} />
      <SecurityKeyDialog open={dialog === "key-add"} onOpenChange={(open) => !open && setDialog(null)} />
      <SecurityKeyDialog
        open={removingKey !== null}
        removing={removingKey ?? undefined}
        onOpenChange={(open) => !open && setRemovingKey(null)}
      />
    </Card>
  );
}
