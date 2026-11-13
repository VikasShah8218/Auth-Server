import { getRouteApi, Link } from "@tanstack/react-router";
import { Ban, CircleCheck, KeyRound, Pencil, RefreshCw } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { useClient, useRotateClientSecret, useUpdateClient } from "@/api/clients";
import { ClientTypeBadge } from "@/components/common/ClientsTable";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { PageHeader } from "@/components/common/PageHeader";
import { ErrorState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { usePageMeta } from "@/components/layout/page-meta";
import { Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/format";

import { ClientDialog } from "./components/ClientDialog";
import { SecretDialog } from "./components/SecretDialog";

const route = getRouteApi("/_app/_admin/clients/$clientId");

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 border-t border-line py-3 first:border-t-0 first:pt-0 sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-4">
      <dt className="text-[13px] text-muted">{label}</dt>
      <dd className="m-0 min-w-0">{children}</dd>
    </div>
  );
}

const none = <span className="text-muted">None</span>;

export default function ClientDetail() {
  const { clientId } = route.useParams();
  const client = useClient(clientId);
  const update = useUpdateClient(clientId);
  const rotate = useRotateClientSecret(clientId);
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState<"rotate" | "toggle" | null>(null);
  const [secret, setSecret] = useState<string | null>(null);

  usePageMeta({ label: "Clients", to: "/clients" }, { label: clientId });

  if (client.isError) return <ErrorState error={client.error} onRetry={() => client.refetch()} />;
  if (client.isPending) return <Skeleton className="h-64 w-full rounded-card" />;
  const c = client.data;
  const confidential = c.type === "confidential";
  const isConsole = c.client_id === "auth-console";

  return (
    <>
      <PageHeader
        eyebrow={`${c.client_id} · created ${formatDate(c.created_at)}`}
        title={c.name}
        actions={
          !isConsole && (
            <>
              <Button onClick={() => setEditing(true)}>
                <Pencil />
                Edit
              </Button>
              {confidential && c.is_active && (
                <Button onClick={() => setConfirm("rotate")}>
                  <RefreshCw />
                  Rotate secret
                </Button>
              )}
              {c.is_active ? (
                <Button variant="danger-ghost" onClick={() => setConfirm("toggle")}>
                  <Ban />
                  Disable
                </Button>
              ) : (
                <Button onClick={() => setConfirm("toggle")}>
                  <CircleCheck />
                  Enable
                </Button>
              )}
            </>
          )
        }
      >
        <div className="mt-2 flex flex-wrap gap-2">
          <StatusBadge status={c.is_active ? "active" : "disabled"} />
          <ClientTypeBadge type={c.type} />
        </div>
      </PageHeader>

      <Card>
        <CardHeader
          title="Settings"
          description={
            isConsole ? "This is the admin console's own client. It's managed by the server." : undefined
          }
        />
        <CardBody>
          <dl className="m-0">
            <Detail label="Application">
              <Link to="/applications/$key" params={{ key: c.app_key }} className="no-underline">
                <Chip>{c.app_key}</Chip>
              </Link>
            </Detail>
            <Detail label="Authentication">
              {confidential ? (
                <span className="flex items-center gap-1.5">
                  <KeyRound className="size-4 text-muted" />
                  Client secret (stored hashed; rotate to get a new one)
                </span>
              ) : (
                "None: signs users in with PKCE"
              )}
            </Detail>
            <Detail label="Redirect URIs">
              {c.redirect_uris.length ? (
                <ul className="m-0 grid list-none gap-1 p-0">
                  {c.redirect_uris.map((uri) => (
                    <li key={uri} className="font-mono text-[13px] break-all">
                      {uri}
                    </li>
                  ))}
                </ul>
              ) : (
                none
              )}
            </Detail>
            <Detail label="Scopes">
              {c.scopes.length ? (
                <div className="flex flex-wrap gap-1">
                  {c.scopes.map((s) => (
                    <Chip key={s}>{s}</Chip>
                  ))}
                </div>
              ) : (
                none
              )}
            </Detail>
            {confidential && (
              <Detail label="Audiences">
                {c.audiences.length ? (
                  <div className="flex flex-wrap gap-1">
                    {c.audiences.map((a) => (
                      <Chip key={a}>{a}</Chip>
                    ))}
                  </div>
                ) : (
                  none
                )}
              </Detail>
            )}
          </dl>
        </CardBody>
      </Card>

      <ClientDialog open={editing} onOpenChange={setEditing} client={c} />
      <ConfirmDialog
        open={confirm === "rotate"}
        onOpenChange={() => setConfirm(null)}
        tone="accent"
        icon={<RefreshCw />}
        title={`Rotate the secret for ${c.client_id}?`}
        description="The old secret and every token issued with it stop working at once. Update the server with the new secret straight away."
        confirmLabel="Rotate secret"
        pending={rotate.isPending}
        error={rotate.error}
        onConfirm={() =>
          rotate.mutate(undefined, {
            onSuccess: (result) => {
              setConfirm(null);
              setSecret(result.client_secret ?? null);
            },
          })
        }
      />
      <ConfirmDialog
        open={confirm === "toggle"}
        onOpenChange={() => setConfirm(null)}
        tone={c.is_active ? "danger" : "accent"}
        icon={c.is_active ? <Ban /> : <CircleCheck />}
        title={c.is_active ? `Disable ${c.client_id}?` : `Enable ${c.client_id}?`}
        description={
          c.is_active
            ? "It can't get tokens any more, and the tokens it issued are rejected everywhere within seconds."
            : "It can get tokens again with its current secret and settings."
        }
        confirmLabel={c.is_active ? "Disable client" : "Enable client"}
        pending={update.isPending}
        error={update.error}
        onConfirm={() =>
          update.mutate(
            { is_active: !c.is_active },
            {
              onSuccess: () => {
                setConfirm(null);
                toast.success(c.is_active ? "Client disabled" : "Client enabled");
              },
            },
          )
        }
      />
      <SecretDialog clientId={c.client_id} secret={secret} onClose={() => setSecret(null)} />
    </>
  );
}
