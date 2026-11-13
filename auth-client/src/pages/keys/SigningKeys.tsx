import { KeyRound, RefreshCw, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import type { Schemas } from "@/api/client";
import { useRevokeKey, useRotateKey, useSigningKeys } from "@/api/operations";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { CopyButton } from "@/components/common/CopyButton";
import { DataTable } from "@/components/common/DataTable";
import { FormField } from "@/components/common/FormField";
import { PageHeader } from "@/components/common/PageHeader";
import { EmptyState, ErrorState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { usePageMeta } from "@/components/layout/page-meta";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";

type Key = Schemas["SigningKeyOut"];

const STATUS_NOTE: Record<string, string> = {
  next: "Published, not signing yet",
  active: "Signs every new token",
  retired: "Still verifies tokens it signed",
  revoked: "Rejected everywhere",
};

export default function SigningKeys() {
  usePageMeta({ label: "Signing keys" });
  const keys = useSigningKeys();
  const rotate = useRotateKey();
  const revoke = useRevokeKey();
  const [rotating, setRotating] = useState(false);
  const [revoking, setRevoking] = useState<Key | null>(null);
  const [typed, setTyped] = useState("");

  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title="Signing keys"
        description="ES256 keys that sign every token. They rotate on a schedule; downstream servers fetch the public halves automatically."
        actions={
          <Button variant="primary" onClick={() => setRotating(true)}>
            <RefreshCw />
            Rotate now
          </Button>
        }
      />
      <Card>
        <CardHeader
          title="Keys"
          description="Expired keys are hidden. A retired key leaves the list once every token it signed has expired."
        />
        {keys.isError ? (
          <ErrorState error={keys.error} onRetry={() => keys.refetch()} />
        ) : (
          <DataTable<Key>
            caption="Signing keys"
            loading={keys.isPending}
            rows={keys.data}
            rowKey={(k) => k.kid}
            skeletonRows={3}
            empty={
              <EmptyState
                icon={KeyRound}
                title="No keys"
                description="The server creates its keys on startup."
              />
            }
            columns={[
              {
                key: "kid",
                header: "Key ID",
                primary: true,
                cell: (k) => (
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-[13px] break-all">{k.kid}</span>
                    <CopyButton value={k.kid} label="Copy key ID" />
                  </div>
                ),
              },
              {
                key: "status",
                header: "Status",
                cell: (k) => (
                  <span className="flex flex-col items-end gap-1 md:items-start">
                    <StatusBadge status={k.status} />
                    <span className="text-xs text-muted">{STATUS_NOTE[k.status]}</span>
                  </span>
                ),
              },
              { key: "activated", header: "Activated", cell: (k) => formatDateTime(k.activated_at) },
              {
                key: "until",
                header: "Rotates / leaves",
                label: "Until",
                cell: (k) => formatDateTime(k.rotates_at ?? k.not_after),
              },
              {
                key: "actions",
                header: <span className="sr-only">Actions</span>,
                actions: true,
                cell: (k) =>
                  k.status === "revoked" ? null : (
                    <Button variant="danger-ghost" size="sm" onClick={() => setRevoking(k)}>
                      Revoke
                    </Button>
                  ),
              },
            ]}
          />
        )}
      </Card>

      <ConfirmDialog
        open={rotating}
        onOpenChange={setRotating}
        tone="accent"
        icon={<RefreshCw />}
        title="Rotate the signing key now?"
        description="The next key becomes active. Tokens signed by the current key keep working until they expire, so nobody is signed out."
        confirmLabel="Rotate key"
        pending={rotate.isPending}
        error={rotate.error}
        onConfirm={() =>
          rotate.mutate(undefined, {
            onSuccess: () => {
              setRotating(false);
              toast.success("Signing key rotated");
            },
          })
        }
      />

      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRevoking(null);
            setTyped("");
          }
        }}
        icon={<ShieldAlert />}
        title="Revoke this key?"
        description="Use this only if the key has leaked. Every token it signed stops working at once, here and on every downstream server, so people signed in with those tokens must sign in again."
        confirmLabel="Revoke key"
        pending={revoke.isPending}
        error={revoke.error}
        onConfirm={() => {
          if (!revoking || typed !== revoking.kid) return;
          revoke.mutate(revoking.kid, {
            onSuccess: () => {
              setRevoking(null);
              setTyped("");
              toast.success("Key revoked");
            },
          });
        }}
      >
        <FormField
          label={
            <>
              Type <span className="font-mono">{revoking?.kid}</span> to confirm
            </>
          }
          error={typed && typed !== revoking?.kid ? "The key ID doesn't match." : undefined}
        >
          <Input
            className="font-mono"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            autoComplete="off"
          />
        </FormField>
      </ConfirmDialog>
    </>
  );
}
