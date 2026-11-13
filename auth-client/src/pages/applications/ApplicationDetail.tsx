import { getRouteApi } from "@tanstack/react-router";
import { Ban, CircleCheck, Pencil } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useApplication, usePermissions, useRoles, useUpdateApplication } from "@/api/applications";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { PageHeader } from "@/components/common/PageHeader";
import { ErrorState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { usePageMeta } from "@/components/layout/page-meta";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDate } from "@/lib/format";

import { ApplicationDialog } from "./components/ApplicationDialog";
import { ClientsTab } from "./components/ClientsTab";
import { MembersTab } from "./components/MembersTab";
import { PermissionsTab } from "./components/PermissionsTab";
import { RolesTab } from "./components/RolesTab";

const route = getRouteApi("/_app/_admin/applications/$key");
const TABS = ["permissions", "roles", "members", "clients"] as const;

export default function ApplicationDetail() {
  const { key: rawKey } = route.useParams();
  const key = rawKey.toUpperCase();
  const { tab } = route.useSearch();
  const navigate = route.useNavigate();
  const app = useApplication(key);
  const permissions = usePermissions(key);
  const roles = useRoles(key);
  const update = useUpdateApplication(key);
  const [editing, setEditing] = useState(false);
  const [toggling, setToggling] = useState(false);

  usePageMeta({ label: "Applications", to: "/applications" }, { label: key });

  const current = TABS.includes(tab as (typeof TABS)[number]) ? (tab as string) : "permissions";
  const setTab = (next: string) =>
    navigate({ search: { tab: next === "permissions" ? undefined : next }, replace: true });

  if (app.isError) return <ErrorState error={app.error} onRetry={() => app.refetch()} />;
  if (app.isPending) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full rounded-card" />
      </div>
    );
  }

  const a = app.data;
  // The console's own application can't be switched off, or nobody could sign in to fix it.
  const isConsoleApp = a.key === "AUTH";
  const livePermissions = permissions.data?.length;

  return (
    <>
      <PageHeader
        eyebrow={`${a.key} · permission map v${a.perm_map_version} · created ${formatDate(a.created_at)}`}
        title={a.name}
        description={a.description || undefined}
        actions={
          <>
            <Button onClick={() => setEditing(true)}>
              <Pencil />
              Edit
            </Button>
            {!isConsoleApp &&
              (a.is_active ? (
                <Button variant="danger-ghost" onClick={() => setToggling(true)}>
                  <Ban />
                  Deactivate
                </Button>
              ) : (
                <Button onClick={() => setToggling(true)}>
                  <CircleCheck />
                  Activate
                </Button>
              ))}
          </>
        }
      >
        <div className="mt-2">
          <StatusBadge status={a.is_active ? "active" : "disabled"} />
        </div>
      </PageHeader>

      <Tabs value={current} onValueChange={setTab}>
        <TabsList aria-label="Application sections">
          <TabsTrigger value="permissions" count={livePermissions}>
            Permissions
          </TabsTrigger>
          <TabsTrigger value="roles" count={roles.data?.length}>
            Roles
          </TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
          <TabsTrigger value="clients">Clients</TabsTrigger>
        </TabsList>
        <TabsContent value="permissions">
          <PermissionsTab appKey={key} />
        </TabsContent>
        <TabsContent value="roles">
          <RolesTab appKey={key} />
        </TabsContent>
        <TabsContent value="members">
          <MembersTab appKey={key} />
        </TabsContent>
        <TabsContent value="clients">
          <ClientsTab appKey={key} />
        </TabsContent>
      </Tabs>

      <ApplicationDialog open={editing} onOpenChange={setEditing} app={a} />
      <ConfirmDialog
        open={toggling}
        onOpenChange={setToggling}
        tone={a.is_active ? "danger" : "accent"}
        icon={a.is_active ? <Ban /> : <CircleCheck />}
        title={a.is_active ? `Deactivate ${a.key}?` : `Activate ${a.key}?`}
        description={
          a.is_active
            ? "Nobody can sign in to it, its clients stop getting tokens, and its tokens are rejected here. Its permissions, roles and members are kept."
            : "People with a role in it can sign in again, and its clients get tokens again."
        }
        confirmLabel={a.is_active ? "Deactivate application" : "Activate application"}
        pending={update.isPending}
        error={update.error}
        onConfirm={() =>
          update.mutate(
            { is_active: !a.is_active },
            {
              onSuccess: () => {
                setToggling(false);
                toast.success(a.is_active ? "Application deactivated" : "Application activated");
              },
            },
          )
        }
      />
    </>
  );
}
