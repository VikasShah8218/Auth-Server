import { getRouteApi, Link } from "@tanstack/react-router";
import { AppWindow, Plus } from "lucide-react";
import { useState } from "react";

import { PAGE_SIZE, useApplications } from "@/api/applications";
import type { Schemas } from "@/api/client";
import { DataTable } from "@/components/common/DataTable";
import { PageHeader } from "@/components/common/PageHeader";
import { Pagination } from "@/components/common/Pagination";
import { EmptyState, ErrorState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { usePageMeta } from "@/components/layout/page-meta";
import { Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatDate } from "@/lib/format";

import { ApplicationDialog } from "./components/ApplicationDialog";

const route = getRouteApi("/_app/_admin/applications");
type Row = Schemas["ApplicationOut"];

export default function ApplicationsList() {
  usePageMeta({ label: "Applications" });
  const { offset = 0 } = route.useSearch();
  const navigate = route.useNavigate();
  const apps = useApplications(offset);
  const [creating, setCreating] = useState(false);

  return (
    <>
      <PageHeader
        eyebrow="Access"
        title="Applications"
        description="Each system that trusts this server. Permissions and roles are defined per application."
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus />
            New application
          </Button>
        }
      />
      <Card>
        {apps.isError ? (
          <ErrorState error={apps.error} onRetry={() => apps.refetch()} />
        ) : (
          <DataTable<Row>
            caption="Applications"
            loading={apps.isPending}
            rows={apps.data?.items}
            rowKey={(a) => a.key}
            empty={
              <EmptyState
                icon={AppWindow}
                title="No applications yet"
                description="Add an application, then create its permissions and roles."
              />
            }
            columns={[
              {
                key: "app",
                header: "Application",
                primary: true,
                cell: (a) => (
                  <div className="flex min-w-0 items-center gap-2.5">
                    <Chip>{a.key}</Chip>
                    <Link
                      to="/applications/$key"
                      params={{ key: a.key }}
                      className="font-medium no-underline hover:underline hover:underline-offset-3"
                    >
                      {a.name}
                    </Link>
                  </div>
                ),
              },
              {
                key: "description",
                header: "Description",
                cell: (a) => <span className="text-fg-2">{a.description || "—"}</span>,
              },
              {
                key: "map",
                header: "Permission map",
                label: "Map version",
                cell: (a) => <span className="font-mono text-[12.5px]">v{a.perm_map_version}</span>,
              },
              {
                key: "status",
                header: "Status",
                cell: (a) => <StatusBadge status={a.is_active ? "active" : "disabled"} />,
              },
              { key: "created", header: "Created", cell: (a) => formatDate(a.created_at) },
            ]}
          />
        )}
        {apps.data && apps.data.total > PAGE_SIZE && (
          <Pagination
            offset={offset}
            limit={PAGE_SIZE}
            total={apps.data.total}
            onChange={(next) => navigate({ search: { offset: next || undefined } })}
          />
        )}
      </Card>
      <ApplicationDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
