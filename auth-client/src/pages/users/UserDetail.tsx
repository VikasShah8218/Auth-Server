import { getRouteApi } from "@tanstack/react-router";
import { Ellipsis, Lock, LogOut, ShieldCheck, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  useEndUserSessions,
  useResetMfa,
  useUpdateUser,
  useUser,
  useUserFactors,
  useUserSessions,
} from "@/api/users";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { PageHeader } from "@/components/common/PageHeader";
import { ErrorState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { usePageMeta } from "@/components/layout/page-meta";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fullName, userInitials } from "@/lib/format";

import { AccessTab } from "./components/AccessTab";
import { MfaTab } from "./components/MfaTab";
import { ProfileTab } from "./components/ProfileTab";
import { SessionsTab } from "./components/SessionsTab";

const route = getRouteApi("/_app/_admin/users/$id");
const TABS = ["access", "sessions", "mfa", "profile"] as const;
type Confirm = "end-sessions" | "reset-mfa" | "disable" | "enable" | null;

export default function UserDetail() {
  const { id } = route.useParams();
  const { tab } = route.useSearch();
  const navigate = route.useNavigate();
  const user = useUser(id);
  const sessions = useUserSessions(id);
  const factors = useUserFactors(id);
  const update = useUpdateUser(id);
  const endSessions = useEndUserSessions(id);
  const resetMfa = useResetMfa(id);
  const [confirm, setConfirm] = useState<Confirm>(null);

  const current = TABS.includes(tab as (typeof TABS)[number]) ? (tab as string) : "access";
  const setTab = (next: string) =>
    navigate({ search: { tab: next === "access" ? undefined : next }, replace: true });

  usePageMeta({ label: "Users", to: "/users" }, { label: user.data?.username ?? "User" });

  if (user.isError) return <ErrorState error={user.error} onRetry={() => user.refetch()} />;
  if (user.isPending) {
    return (
      <div className="grid gap-4">
        <div className="flex items-center gap-4">
          <Skeleton className="size-14 rounded-full" />
          <div className="grid gap-2">
            <Skeleton className="h-3 w-64" />
            <Skeleton className="h-7 w-48" />
          </div>
        </div>
        <Skeleton className="h-64 w-full rounded-card" />
      </div>
    );
  }

  const u = user.data;
  const name = fullName(u) || u.username;
  const mfaOn = (factors.data?.length ?? 0) > 0;
  const liveSessions = sessions.data?.length ?? 0;

  const close = () => setConfirm(null);
  const done = (message: string) => () => {
    close();
    toast.success(message);
  };

  return (
    <>
      <PageHeader
        leading={
          <Avatar size="lg" muted={!u.is_active}>
            {userInitials(u)}
          </Avatar>
        }
        eyebrow={`${u.username} · ${u.public_id}`}
        title={name}
        actions={
          <>
            <Button onClick={() => setConfirm("end-sessions")} disabled={liveSessions === 0}>
              <LogOut />
              End all sessions
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="icon" aria-label="More actions">
                  <Ellipsis />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem onSelect={() => setTab("profile")}>
                  <Lock />
                  Set a new password
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setConfirm("reset-mfa")} disabled={!mfaOn}>
                  <ShieldCheck />
                  Reset MFA
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                {u.is_active ? (
                  <DropdownMenuItem tone="danger" onSelect={() => setConfirm("disable")}>
                    <UserX />
                    Disable user
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onSelect={() => setConfirm("enable")}>
                    <UserCheck />
                    Enable user
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      >
        <div className="mt-2 flex flex-wrap gap-2">
          <StatusBadge status={u.is_active ? "active" : "disabled"} />
          {factors.data && (
            <Badge tone={mfaOn ? "accent" : "neutral"}>
              <ShieldCheck />
              {mfaOn ? "MFA on" : "MFA off"}
            </Badge>
          )}
          {sessions.data && (
            <Badge>
              {liveSessions} live session{liveSessions === 1 ? "" : "s"}
            </Badge>
          )}
        </div>
      </PageHeader>

      <Tabs value={current} onValueChange={setTab}>
        <TabsList aria-label="User sections">
          <TabsTrigger value="access" count={u.applications.length}>
            Access
          </TabsTrigger>
          <TabsTrigger value="sessions" count={sessions.data?.length}>
            Sessions
          </TabsTrigger>
          <TabsTrigger value="mfa" count={factors.data?.length}>
            MFA
          </TabsTrigger>
          <TabsTrigger value="profile">Profile</TabsTrigger>
        </TabsList>
        <TabsContent value="access">
          <AccessTab user={u} />
        </TabsContent>
        <TabsContent value="sessions">
          <SessionsTab userId={id} name={u.first_name || u.username} query={sessions} />
        </TabsContent>
        <TabsContent value="mfa">
          <MfaTab name={u.first_name || u.username} query={factors} onReset={() => setConfirm("reset-mfa")} />
        </TabsContent>
        <TabsContent value="profile">
          <ProfileTab user={u} />
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={confirm === "end-sessions"}
        onOpenChange={close}
        icon={<LogOut />}
        title={`End all sessions for ${u.username}?`}
        description={`${name} is signed out on every device. Connected apps reject the tokens within seconds.`}
        confirmLabel="End all sessions"
        pending={endSessions.isPending}
        error={endSessions.error}
        onConfirm={() => endSessions.mutate(undefined, { onSuccess: done("All sessions ended") })}
      />
      <ConfirmDialog
        open={confirm === "reset-mfa"}
        onOpenChange={close}
        icon={<ShieldCheck />}
        title={`Reset MFA for ${u.username}?`}
        description={`This removes every authenticator app and security key, and ends all ${liveSessions} live session${liveSessions === 1 ? "" : "s"}. MFA is set up again after the next sign-in.`}
        confirmLabel="Reset MFA"
        pending={resetMfa.isPending}
        error={resetMfa.error}
        onConfirm={() => resetMfa.mutate(undefined, { onSuccess: done("MFA reset") })}
      />
      <ConfirmDialog
        open={confirm === "disable"}
        onOpenChange={close}
        icon={<UserX />}
        title={`Disable ${u.username}?`}
        description={`${name} is signed out everywhere at once, and every connected app rejects the account's tokens within seconds. You can enable the account again later.`}
        confirmLabel="Disable user"
        pending={update.isPending}
        error={update.error}
        onConfirm={() => update.mutate({ is_active: false }, { onSuccess: done("User disabled") })}
      />
      <ConfirmDialog
        open={confirm === "enable"}
        onOpenChange={close}
        tone="accent"
        icon={<UserCheck />}
        title={`Enable ${u.username}?`}
        description={`${name} can sign in again with the same roles as before.`}
        confirmLabel="Enable user"
        pending={update.isPending}
        error={update.error}
        onConfirm={() => update.mutate({ is_active: true }, { onSuccess: done("User enabled") })}
      />
    </>
  );
}
