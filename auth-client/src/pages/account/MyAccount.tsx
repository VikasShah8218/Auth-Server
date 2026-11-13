import { getRouteApi } from "@tanstack/react-router";
import { AppWindow } from "lucide-react";
import { toast } from "sonner";

import { useEndMySession, useMe, useMySessions } from "@/api/account";
import { useSession } from "@/api/session";
import { heldSummary, KeyCut } from "@/components/common/KeyCut";
import { PageHeader } from "@/components/common/PageHeader";
import { SessionList } from "@/components/common/SessionList";
import { EmptyState, ErrorState } from "@/components/common/States";
import { usePageMeta } from "@/components/layout/page-meta";
import { Avatar } from "@/components/ui/avatar";
import { Badge, Chip } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { userMessage } from "@/lib/errors";
import { formatDate, fullName, userInitials } from "@/lib/format";

import { ChangePassword } from "./components/ChangePassword";
import { MfaSettings } from "./components/MfaSettings";

const route = getRouteApi("/_app/account");
const TABS = ["profile", "security", "sessions"] as const;

function AccessList() {
  const me = useMe();
  if (me.isError) return <ErrorState error={me.error} onRetry={() => me.refetch()} />;
  if (me.isPending) return <Skeleton className="h-40 w-full rounded-card" />;
  if (me.data.applications.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={AppWindow}
          title="No application access yet"
          description="You can manage your own account here. Ask an administrator for a role in the applications you use."
        />
      </Card>
    );
  }
  return (
    <div className="grid gap-4">
      {me.data.applications.map((app) => (
        <Card key={app.app_key}>
          <CardHeader
            leading={<Chip>{app.app_key}</Chip>}
            title={app.app_name}
            description={`${app.roles.map((r) => r.name).join(", ")} · ${heldSummary(app.bits)}`}
          />
          <CardBody className="grid grid-cols-1 items-start gap-5 md:grid-cols-[auto_minmax(0,1fr)] md:gap-8">
            <KeyCut bits={app.bits} />
            <div className="flex flex-wrap gap-1">
              {app.permissions.map((code) => (
                <Chip key={code}>{code === "*" ? "* (full access)" : code}</Chip>
              ))}
            </div>
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

function MySessions() {
  const sessions = useMySessions();
  const end = useEndMySession();
  return (
    <Card>
      <CardHeader
        title="Where you're signed in"
        description="Signing out a device ends that session everywhere. Changing your password signs out all other devices."
      />
      <SessionList
        query={sessions}
        endLabel="Sign out"
        ending={end.isPending ? (end.variables ?? null) : null}
        onEnd={(session) =>
          end.mutate(session.id, {
            onSuccess: () => toast.success("Device signed out"),
            onError: (error) => toast.error(userMessage(error)),
          })
        }
      />
    </Card>
  );
}

export default function MyAccount() {
  usePageMeta({ label: "My account" });
  const session = useSession();
  const me = useMe();
  const { tab } = route.useSearch();
  const navigate = route.useNavigate();
  const current = TABS.includes(tab as (typeof TABS)[number]) ? (tab as string) : "profile";
  const user = me.data ?? session.user;

  return (
    <>
      <PageHeader
        leading={<Avatar size="lg">{userInitials(user)}</Avatar>}
        eyebrow={`${user.username} · ${session.user.public_id}`}
        title={fullName(user) || user.username}
        description={user.email ?? undefined}
      >
        <div className="mt-2 flex flex-wrap gap-2">
          {session.is_admin && <Badge tone="accent">Administrator</Badge>}
          {me.data && <Badge>Member since {formatDate(me.data.created_at)}</Badge>}
        </div>
      </PageHeader>

      <Tabs
        value={current}
        onValueChange={(next) =>
          navigate({ search: { tab: next === "profile" ? undefined : next }, replace: true })
        }
      >
        <TabsList aria-label="Account sections">
          <TabsTrigger value="profile">Access</TabsTrigger>
          <TabsTrigger value="security">Password and MFA</TabsTrigger>
          <TabsTrigger value="sessions">Devices</TabsTrigger>
        </TabsList>
        <TabsContent value="profile">
          <AccessList />
        </TabsContent>
        <TabsContent value="security">
          <div className="grid gap-4">
            <MfaSettings />
            <ChangePassword username={user.username} />
          </div>
        </TabsContent>
        <TabsContent value="sessions">
          <MySessions />
        </TabsContent>
      </Tabs>
    </>
  );
}
