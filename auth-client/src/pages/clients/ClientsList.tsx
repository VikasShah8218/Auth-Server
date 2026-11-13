import { getRouteApi, useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useApplicationOptions } from "@/api/applications";
import { useClients } from "@/api/clients";
import { ClientsTable } from "@/components/common/ClientsTable";
import { TableToolbar } from "@/components/common/DataTable";
import { PageHeader } from "@/components/common/PageHeader";
import { usePageMeta } from "@/components/layout/page-meta";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";

import { ClientDialog } from "./components/ClientDialog";
import { SecretDialog } from "./components/SecretDialog";

const route = getRouteApi("/_app/_admin/clients");

export default function ClientsList() {
  usePageMeta({ label: "Clients" });
  const { app } = route.useSearch();
  const navigate = useNavigate();
  const apps = useApplicationOptions();
  const clients = useClients(app);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<{ clientId: string; secret: string } | null>(null);

  return (
    <>
      <PageHeader
        eyebrow="Access"
        title="Clients"
        description="Browser apps sign users in. Servers use a secret to follow events and call other servers."
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus />
            New client
          </Button>
        }
      />
      <Card>
        <TableToolbar>
          <label>
            <span className="sr-only">Application</span>
            <Select
              value={app ?? ""}
              onChange={(event) =>
                navigate({ to: "/clients", search: { app: event.target.value || undefined } })
              }
            >
              <option value="">All applications</option>
              {apps.data?.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.key}
                </option>
              ))}
            </Select>
          </label>
        </TableToolbar>
        <ClientsTable query={clients} />
      </Card>

      <ClientDialog
        open={creating}
        onOpenChange={setCreating}
        defaultApp={app}
        onCreated={(result) => {
          if (result.client_secret)
            setCreated({ clientId: result.client.client_id, secret: result.client_secret });
          else {
            toast.success("Client created");
            navigate({ to: "/clients/$clientId", params: { clientId: result.client.client_id } });
          }
        }}
      />
      <SecretDialog
        clientId={created?.clientId ?? ""}
        secret={created?.secret ?? null}
        onClose={() => {
          const id = created?.clientId;
          setCreated(null);
          if (id) navigate({ to: "/clients/$clientId", params: { clientId: id } });
        }}
      />
    </>
  );
}
