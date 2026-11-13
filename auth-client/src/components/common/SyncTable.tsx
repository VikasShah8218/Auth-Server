import type { UseQueryResult } from "@tanstack/react-query";
import { Server } from "lucide-react";
import type { ReactNode } from "react";

import type { Schemas } from "@/api/client";
import { DataTable } from "@/components/common/DataTable";
import { Tile } from "@/components/common/ListRow";
import { EmptyState, ErrorState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Chip } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { formatNumber, formatRelative } from "@/lib/format";

type Row = Schemas["DownstreamOut"];

/** Each downstream instance: last acknowledged event, how far behind, and when it was last heard from. */
export function SyncTable({
  query,
  limit,
  action,
}: {
  query: UseQueryResult<Row[]>;
  limit?: number;
  action?: ReactNode;
}) {
  const rows = query.data && limit ? query.data.slice(0, limit) : query.data;

  return (
    <Card>
      <CardHeader
        title="Downstream sync"
        description="Each server's last acknowledged event and how far behind it is."
        actions={action}
      />
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : (
        <DataTable<Row>
          caption="Downstream servers"
          loading={query.isPending}
          rows={rows}
          rowKey={(r) => `${r.client_id}/${r.instance_id}`}
          skeletonRows={3}
          empty={
            <EmptyState
              icon={Server}
              title="No downstream servers yet"
              description="A server appears here once its SDK connects with a confidential client that has the events.read scope."
            />
          }
          columns={[
            {
              key: "server",
              header: "Server",
              primary: true,
              cell: (r) => (
                <div className="flex items-center gap-2.5">
                  <Tile>
                    <Server />
                  </Tile>
                  <div className="min-w-0">
                    <div className="font-mono text-[13px]">{r.client_id}</div>
                    <div className="font-mono text-xs text-muted">{r.instance_id}</div>
                  </div>
                </div>
              ),
            },
            { key: "app", header: "App", cell: (r) => <Chip>{r.app_key}</Chip> },
            { key: "ack", header: "Last ACK", numeric: true, cell: (r) => formatNumber(r.last_acked_seq) },
            { key: "lag", header: "Behind", numeric: true, cell: (r) => formatNumber(r.lag) },
            { key: "seen", header: "Last seen", cell: (r) => formatRelative(r.last_seen_at) },
            { key: "status", header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
          ]}
        />
      )}
    </Card>
  );
}
