import { Link } from "@tanstack/react-router";
import { Activity, AppWindow, ChevronRight, Plug, Plus, ScrollText, Users } from "lucide-react";

import { useDownstream, useStats } from "@/api/operations";
import { PageHeader } from "@/components/common/PageHeader";
import { StatStrip } from "@/components/common/StatStrip";
import { usePageMeta } from "@/components/layout/page-meta";
import { Button } from "@/components/ui/button";

import { ActivityCard } from "./components/ActivityCard";
import { SigningKeyCard } from "./components/SigningKeyCard";
import { SyncTable } from "@/components/common/SyncTable";

function syncSentence(
  rows: { status: string; client_id: string; instance_id: string }[] | undefined,
): string {
  if (!rows) return "Loading the state of your downstream servers.";
  if (rows.length === 0) return "No downstream servers have connected yet.";
  const ok = rows.filter((r) => r.status === "ok").length;
  const offline = rows.filter((r) => r.status === "offline");
  let sentence = `${ok} of ${rows.length} downstream server${rows.length === 1 ? " is" : "s are"} in sync.`;
  if (offline.length === 1) sentence += ` ${offline[0].client_id} (${offline[0].instance_id}) is offline.`;
  else if (offline.length > 1) sentence += ` ${offline.length} are offline.`;
  return sentence;
}

export default function Dashboard() {
  usePageMeta({ label: "Dashboard" });
  const stats = useStats();
  const downstream = useDownstream();
  const s = stats.data;

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        description={syncSentence(downstream.data)}
        actions={
          <>
            <Button asChild>
              <Link to="/audit">
                <ScrollText />
                Audit log
              </Link>
            </Button>
            <Button asChild variant="primary">
              <Link to="/users" search={{ create: true }}>
                <Plus />
                New user
              </Link>
            </Button>
          </>
        }
      />

      <StatStrip
        loading={stats.isPending}
        stats={[
          {
            label: "Users",
            icon: Users,
            value: s?.users,
            note: s ? (s.disabled_users ? `${s.disabled_users} disabled` : "all active") : null,
          },
          {
            label: "Applications",
            icon: AppWindow,
            value: s?.applications,
            note: s?.application_keys.join(", "),
          },
          {
            label: "Live sessions",
            icon: Activity,
            value: s?.active_sessions,
            note: s ? `across ${s.session_users} ${s.session_users === 1 ? "person" : "people"}` : null,
          },
          { label: "Service clients", icon: Plug, value: s?.service_clients, note: "active" },
        ]}
      />

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <SyncTable
          query={downstream}
          limit={6}
          action={
            <Button asChild variant="ghost" size="sm">
              <Link to="/downstream">
                View all
                <ChevronRight />
              </Link>
            </Button>
          }
        />
        <div className="grid gap-4">
          <SigningKeyCard />
          <ActivityCard />
        </div>
      </div>
    </>
  );
}
