import { Link } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useRotateKey, useSigningKeys } from "@/api/operations";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { CopyButton } from "@/components/common/CopyButton";
import { ErrorState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { daysUntil, formatShortDate } from "@/lib/format";

export function SigningKeyCard() {
  const keys = useSigningKeys();
  const rotate = useRotateKey();
  const [confirm, setConfirm] = useState(false);
  const active = keys.data?.find((k) => k.status === "active");

  const left = daysUntil(active?.rotates_at);
  const span =
    active?.rotates_at && active.activated_at
      ? (new Date(active.rotates_at).getTime() - new Date(active.activated_at).getTime()) / 86_400_000
      : null;
  const progress = left !== null && span ? Math.min(100, Math.max(0, ((span - left) / span) * 100)) : 0;

  return (
    <Card>
      <CardHeader
        title={
          <Link to="/keys" className="no-underline hover:underline">
            Signing key
          </Link>
        }
        description="ES256 · rotates on schedule"
        actions={active && <StatusBadge status="active" />}
      />
      <CardBody className="grid gap-4">
        {keys.isError ? (
          <ErrorState error={keys.error} onRetry={() => keys.refetch()} />
        ) : !active ? (
          <div className="grid gap-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-2 w-full" />
          </div>
        ) : (
          <>
            <div>
              <div className="flex items-center justify-between text-muted">
                Key ID
                <CopyButton value={active.kid} label="Copy key ID" />
              </div>
              <div className="font-mono break-all">{active.kid}</div>
            </div>
            <div className="grid gap-1.5">
              <div className="flex justify-between text-xs text-muted">
                <span>Next rotation</span>
                <span>
                  <b className="font-medium text-fg-2">
                    {left === null ? "—" : left <= 0 ? "due now" : `${left} day${left === 1 ? "" : "s"}`}
                  </b>
                  {active.rotates_at && ` · ${formatShortDate(active.rotates_at)}`}
                </span>
              </div>
              <progress
                value={Math.round(progress)}
                max={100}
                aria-label="Time until the next rotation"
                className="h-1.5 w-full appearance-none overflow-hidden rounded-full border-0 bg-surface-2 [&::-moz-progress-bar]:rounded-full [&::-moz-progress-bar]:bg-accent [&::-webkit-progress-bar]:bg-surface-2 [&::-webkit-progress-value]:rounded-full [&::-webkit-progress-value]:bg-accent"
              />
            </div>
          </>
        )}
        <Button block onClick={() => setConfirm(true)} disabled={!active}>
          <RefreshCw />
          Rotate now
        </Button>
      </CardBody>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        tone="accent"
        icon={<RefreshCw />}
        title="Rotate the signing key now?"
        description="The next key becomes active and signs new tokens. Tokens signed by the current key keep working until they expire, so nobody is signed out."
        confirmLabel="Rotate key"
        pending={rotate.isPending}
        error={rotate.error}
        onConfirm={() =>
          rotate.mutate(undefined, {
            onSuccess: () => {
              setConfirm(false);
              toast.success("Signing key rotated");
            },
          })
        }
      />
    </Card>
  );
}
