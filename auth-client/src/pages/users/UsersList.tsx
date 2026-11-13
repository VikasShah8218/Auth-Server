import { getRouteApi, Link } from "@tanstack/react-router";
import { Plus, Search, Users } from "lucide-react";
import { useEffect, useState } from "react";

import { useApplicationOptions } from "@/api/applications";
import type { Schemas } from "@/api/client";
import { useStats } from "@/api/operations";
import { USERS_PAGE_SIZE, useUsers } from "@/api/users";
import { DataTable, TableToolbar } from "@/components/common/DataTable";
import { PageHeader } from "@/components/common/PageHeader";
import { Pagination } from "@/components/common/Pagination";
import { EmptyState, ErrorState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { usePageMeta } from "@/components/layout/page-meta";
import { Avatar } from "@/components/ui/avatar";
import { Badge, Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { formatDate, formatNumber, fullName, userInitials } from "@/lib/format";

import { CreateUserDialog } from "./components/CreateUserDialog";

const route = getRouteApi("/_app/_admin/users");

type Row = Schemas["UserListItem"];

export default function UsersList() {
  usePageMeta({ label: "Users" });
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const stats = useStats();
  const apps = useApplicationOptions();

  const [text, setText] = useState(search.q ?? "");
  const debounced = useDebouncedValue(text);
  useEffect(() => {
    if ((debounced || undefined) !== search.q) {
      navigate({
        search: (prev) => ({ ...prev, q: debounced || undefined, offset: undefined }),
        replace: true,
      });
    }
  }, [debounced, search.q, navigate]);

  const offset = search.offset ?? 0;
  const users = useUsers({ q: search.q, status: search.status, app: search.app, offset });
  const filtered = !!(search.q || search.status || search.app);

  const setFilter = (patch: Partial<typeof search>) =>
    navigate({ search: (prev) => ({ ...prev, ...patch, offset: undefined }) });

  const setCreating = (open: boolean) =>
    navigate({ search: (prev) => ({ ...prev, create: open || undefined }), replace: true });

  return (
    <>
      <PageHeader
        eyebrow="Access"
        title="Users"
        description={
          stats.data
            ? `${formatNumber(stats.data.users)} people · ${formatNumber(stats.data.disabled_users)} disabled. Roles are set per application on each user's page.`
            : "Roles are set per application on each user's page."
        }
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus />
            New user
          </Button>
        }
      />

      <Card>
        <TableToolbar>
          <label className="relative min-w-[220px] flex-[1_1_260px]">
            <span className="sr-only">Search users</span>
            <Search className="pointer-events-none absolute top-1/2 left-[11px] size-4 -translate-y-1/2 text-muted" />
            <Input
              className="h-9 pl-[34px]"
              placeholder="Search by username, name or email"
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <label>
            <span className="sr-only">Status</span>
            <Select
              value={search.status ?? ""}
              onChange={(event) =>
                setFilter({ status: (event.target.value || undefined) as typeof search.status })
              }
            >
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
            </Select>
          </label>
          <label>
            <span className="sr-only">Application</span>
            <Select
              value={search.app ?? ""}
              onChange={(event) => setFilter({ app: event.target.value || undefined })}
            >
              <option value="">All applications</option>
              {apps.data?.map((app) => (
                <option key={app.key} value={app.key}>
                  {app.key}
                </option>
              ))}
            </Select>
          </label>
        </TableToolbar>

        {users.isError ? (
          <ErrorState error={users.error} onRetry={() => users.refetch()} />
        ) : (
          <DataTable<Row>
            caption="Users"
            loading={users.isPending}
            rows={users.data?.items}
            rowKey={(u) => u.public_id}
            empty={
              filtered ? (
                <EmptyState
                  icon={Search}
                  title={search.q ? `No users match "${search.q}"` : "No users match these filters"}
                  description="Check the spelling, or clear the filters to see everyone."
                  action={
                    <Button
                      size="sm"
                      onClick={() => {
                        setText("");
                        navigate({ search: {} });
                      }}
                    >
                      Clear filters
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon={Users}
                  title="No users yet"
                  description="Create the people who sign in, then give them roles in each application."
                  action={
                    <Button size="sm" variant="primary" onClick={() => setCreating(true)}>
                      <Plus />
                      New user
                    </Button>
                  }
                />
              )
            }
            columns={[
              {
                key: "user",
                header: "User",
                primary: true,
                cell: (u) => (
                  <div className="flex min-w-0 items-center gap-2.5">
                    <Avatar muted={!u.is_active}>{userInitials(u)}</Avatar>
                    <div className="min-w-0">
                      <Link
                        to="/users/$id"
                        params={{ id: u.public_id }}
                        className="font-medium no-underline hover:underline hover:underline-offset-3"
                      >
                        {u.username}
                      </Link>
                      {fullName(u) && <div className="text-xs text-muted">{fullName(u)}</div>}
                    </div>
                  </div>
                ),
              },
              {
                key: "email",
                header: "Email",
                cell: (u) =>
                  u.email ? (
                    <span className="break-all">{u.email}</span>
                  ) : (
                    <span className="text-muted">None</span>
                  ),
              },
              {
                key: "apps",
                header: "Applications",
                cell: (u) =>
                  u.app_keys.length ? (
                    <div className="flex flex-wrap justify-end gap-1 md:justify-start">
                      {u.app_keys.map((key) => (
                        <Chip key={key}>{key}</Chip>
                      ))}
                    </div>
                  ) : (
                    <span className="text-muted">No access yet</span>
                  ),
              },
              {
                key: "mfa",
                header: "MFA",
                cell: (u) => (u.mfa_enabled ? <Badge tone="ok">On</Badge> : <Badge>Off</Badge>),
              },
              {
                key: "status",
                header: "Status",
                cell: (u) => <StatusBadge status={u.is_active ? "active" : "disabled"} />,
              },
              { key: "created", header: "Created", cell: (u) => formatDate(u.created_at) },
            ]}
          />
        )}

        {users.data && users.data.total > 0 && (
          <Pagination
            offset={offset}
            limit={USERS_PAGE_SIZE}
            total={users.data.total}
            onChange={(next) => navigate({ search: (prev) => ({ ...prev, offset: next || undefined }) })}
          />
        )}
      </Card>

      <CreateUserDialog open={!!search.create} onOpenChange={setCreating} />
    </>
  );
}
