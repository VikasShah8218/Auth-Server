import { getRouteApi } from "@tanstack/react-router";
import { ScrollText, X } from "lucide-react";

import { useApplicationOptions } from "@/api/applications";
import type { Schemas } from "@/api/client";
import { AUDIT_PAGE_SIZE, useAudit } from "@/api/operations";
import { DataTable, TableToolbar } from "@/components/common/DataTable";
import { PageHeader } from "@/components/common/PageHeader";
import { Pagination } from "@/components/common/Pagination";
import { EmptyState, ErrorState } from "@/components/common/States";
import { usePageMeta } from "@/components/layout/page-meta";
import { Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { AUDIT_ACTIONS, auditLabel, isAlarming } from "@/lib/audit";
import { formatDateTime } from "@/lib/format";

const route = getRouteApi("/_app/_admin/audit");
type Entry = Schemas["AuditOut"];

function detailsText(details: Entry["details"]): string {
  if (!details) return "";
  return Object.entries(details)
    .map(
      ([key, value]) =>
        `${key}: ${Array.isArray(value) ? value.join(", ") : typeof value === "object" ? JSON.stringify(value) : value}`,
    )
    .join(" · ");
}

export default function AuditLog() {
  usePageMeta({ label: "Audit log" });
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const apps = useApplicationOptions();
  const offset = search.offset ?? 0;
  const audit = useAudit({ actor: search.actor, action: search.action, app: search.app, offset });
  const filtered = !!(search.actor || search.action || search.app);

  const setFilter = (patch: Partial<typeof search>) =>
    navigate({ search: (prev) => ({ ...prev, ...patch, offset: undefined }) });

  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title="Audit log"
        description="Every change to access, newest first. Records can't be edited or deleted."
      />
      <Card>
        <TableToolbar>
          <label>
            <span className="sr-only">Action</span>
            <Select
              value={search.action ?? ""}
              onChange={(event) => setFilter({ action: event.target.value || undefined })}
            >
              <option value="">All actions</option>
              {Object.entries(AUDIT_ACTIONS).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </Select>
          </label>
          <label>
            <span className="sr-only">Application</span>
            <Select
              value={search.app ?? ""}
              onChange={(event) => setFilter({ app: event.target.value || undefined })}
            >
              <option value="">All applications</option>
              {apps.data?.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.key}
                </option>
              ))}
            </Select>
          </label>
          {search.actor && (
            <Button size="sm" className="h-9" onClick={() => setFilter({ actor: undefined })}>
              Actor: {audit.data?.items[0]?.actor_name ?? search.actor}
              <X />
            </Button>
          )}
        </TableToolbar>

        {audit.isError ? (
          <ErrorState error={audit.error} onRetry={() => audit.refetch()} />
        ) : (
          <DataTable<Entry>
            caption="Audit records"
            loading={audit.isPending}
            rows={audit.data?.items}
            rowKey={(e) => String(e.id)}
            empty={
              <EmptyState
                icon={ScrollText}
                title={filtered ? "No records match these filters" : "No records yet"}
                description={
                  filtered ? "Clear a filter to see more." : "Changes to access appear here as they happen."
                }
                action={
                  filtered && (
                    <Button size="sm" onClick={() => navigate({ search: {} })}>
                      Clear filters
                    </Button>
                  )
                }
              />
            }
            columns={[
              {
                key: "action",
                header: "What happened",
                primary: true,
                cell: (e) => (
                  <div className="min-w-0">
                    <div className={isAlarming(e.action) ? "font-medium text-danger" : "font-medium"}>
                      {auditLabel(e.action)}
                    </div>
                    <div className="font-mono text-[11.5px] text-muted">{e.action}</div>
                  </div>
                ),
              },
              {
                key: "actor",
                header: "By",
                cell: (e) => (
                  <button
                    type="button"
                    title="Show only this actor"
                    onClick={() => setFilter({ actor: e.actor })}
                    className="cursor-pointer border-0 bg-transparent p-0 text-left text-fg hover:underline"
                  >
                    {e.actor_name}
                  </button>
                ),
              },
              {
                key: "app",
                header: "App",
                cell: (e) => (e.app ? <Chip>{e.app}</Chip> : <span className="text-muted">—</span>),
              },
              {
                key: "details",
                header: "Details",
                cell: (e) => (
                  <span className="block max-w-[320px] text-xs break-words text-fg-2">
                    {[e.target, detailsText(e.details)].filter(Boolean).join(" · ") || "—"}
                  </span>
                ),
              },
              {
                key: "when",
                header: "When",
                cell: (e) => (
                  <span className="whitespace-nowrap">
                    {formatDateTime(e.created_at)}
                    {e.ip && <span className="block font-mono text-[11.5px] text-muted">{e.ip}</span>}
                  </span>
                ),
              },
            ]}
          />
        )}
        {audit.data && audit.data.total > 0 && (
          <Pagination
            offset={offset}
            limit={AUDIT_PAGE_SIZE}
            total={audit.data.total}
            onChange={(next) => navigate({ search: (prev) => ({ ...prev, offset: next || undefined }) })}
          />
        )}
      </Card>
    </>
  );
}
