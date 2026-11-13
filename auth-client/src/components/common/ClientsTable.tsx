import type { UseQueryResult } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Plug } from "lucide-react";
import type { ReactNode } from "react";

import type { Schemas } from "@/api/client";
import { Badge, Chip } from "@/components/ui/badge";

import { DataTable } from "./DataTable";
import { EmptyState, ErrorState } from "./States";
import { StatusBadge } from "./StatusBadge";

type Client = Schemas["ClientOut"];

export function ClientTypeBadge({ type }: { type: string }) {
  return type === "confidential" ? <Badge tone="info">Server</Badge> : <Badge>Browser app</Badge>;
}

export function ClientsTable({ query, empty }: { query: UseQueryResult<Client[]>; empty?: ReactNode }) {
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  return (
    <DataTable<Client>
      caption="Clients"
      loading={query.isPending}
      rows={query.data}
      rowKey={(c) => c.client_id}
      empty={
        empty ?? (
          <EmptyState
            icon={Plug}
            title="No clients"
            description="Browser apps and downstream servers each need a client to get tokens."
          />
        )
      }
      columns={[
        {
          key: "client",
          header: "Client",
          primary: true,
          cell: (c) => (
            <div className="min-w-0">
              <Link
                to="/clients/$clientId"
                params={{ clientId: c.client_id }}
                className="font-mono text-[13px] font-medium no-underline hover:underline"
              >
                {c.client_id}
              </Link>
              <div className="text-xs text-muted">{c.name}</div>
            </div>
          ),
        },
        { key: "app", header: "App", cell: (c) => <Chip>{c.app_key}</Chip> },
        { key: "type", header: "Type", cell: (c) => <ClientTypeBadge type={c.type} /> },
        {
          key: "scopes",
          header: "Scopes",
          cell: (c) =>
            c.scopes.length ? (
              <div className="flex flex-wrap justify-end gap-1 md:justify-start">
                {c.scopes.map((s) => (
                  <Chip key={s}>{s}</Chip>
                ))}
              </div>
            ) : (
              <span className="text-muted">None</span>
            ),
        },
        {
          key: "status",
          header: "Status",
          cell: (c) => <StatusBadge status={c.is_active ? "active" : "disabled"} />,
        },
      ]}
    />
  );
}
