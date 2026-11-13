import { Link } from "@tanstack/react-router";
import {
  AppWindow,
  KeyRound,
  LayoutDashboard,
  Plug,
  ScrollText,
  Server,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { useDownstream, useStats } from "@/api/operations";
import { useSession } from "@/api/session";
import { cn } from "@/lib/cn";

import { BrandMark } from "./BrandMark";

type Item = {
  to: string;
  label: string;
  icon: LucideIcon;
  count?: ReactNode;
  alert?: boolean;
  exact?: boolean;
};

function NavItem({ to, label, icon: Icon, count, alert, exact }: Item) {
  return (
    <Link
      to={to}
      activeOptions={{ exact: exact ?? false }}
      className={cn(
        "relative flex items-center gap-2.5 rounded-control px-2.5 py-2 text-[13.5px] text-ink-fg no-underline hover:bg-ink-2 hover:text-white",
        "data-[status=active]:bg-ink-2 data-[status=active]:text-white",
        "data-[status=active]:before:absolute data-[status=active]:before:top-2 data-[status=active]:before:bottom-2 data-[status=active]:before:-left-3 data-[status=active]:before:w-[3px] data-[status=active]:before:rounded-r-[3px] data-[status=active]:before:bg-accent data-[status=active]:before:content-['']",
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      {label}
      {count !== undefined && count !== null && (
        <span className={cn("ml-auto font-mono text-[11px]", alert ? "text-warn" : "text-ink-muted")}>
          {count}
        </span>
      )}
    </Link>
  );
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <div className="px-2.5 pt-4 pb-1.5 text-[11px] tracking-[0.08em] text-ink-muted uppercase">{label}</div>
      <div className="grid gap-0.5">{children}</div>
    </>
  );
}

function AdminNav() {
  const stats = useStats();
  const downstream = useDownstream();
  const attention = downstream.data?.filter((d) => d.status !== "ok").length;

  return (
    <>
      <Group label="Overview">
        <NavItem to="/" label="Dashboard" icon={LayoutDashboard} exact />
      </Group>
      <Group label="Access">
        <NavItem to="/applications" label="Applications" icon={AppWindow} count={stats.data?.applications} />
        <NavItem to="/users" label="Users" icon={Users} count={stats.data?.users} />
        <NavItem to="/clients" label="Clients" icon={Plug} count={stats.data?.service_clients} />
      </Group>
      <Group label="Operations">
        <NavItem
          to="/downstream"
          label="Downstream sync"
          icon={Server}
          count={attention ? attention : undefined}
          alert={!!attention}
        />
        <NavItem to="/keys" label="Signing keys" icon={KeyRound} />
        <NavItem to="/audit" label="Audit log" icon={ScrollText} />
      </Group>
    </>
  );
}

export function Sidebar({ open }: { open: boolean }) {
  const session = useSession();

  return (
    <aside
      aria-label="Main navigation"
      className={cn(
        "z-40 flex h-dvh flex-col overflow-y-auto border-r border-ink-line bg-ink px-3 py-4 text-ink-fg",
        "fixed inset-y-0 left-0 w-[264px] transition-transform duration-200 lg:sticky lg:top-0 lg:w-auto lg:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full",
      )}
    >
      <Link
        to={session.is_admin ? "/" : "/account"}
        className="flex items-center gap-2.5 px-2 pt-1 pb-3.5 no-underline"
      >
        <BrandMark />
        <span className="grid">
          <span className="font-display text-[15px] leading-tight font-bold text-white">Auth Server</span>
          <span className="text-[11px] tracking-[0.04em] text-ink-muted">Access console</span>
        </span>
      </Link>

      <nav aria-label="Sections">{session.is_admin ? <AdminNav /> : null}</nav>

      <div className="mt-auto grid gap-0.5 border-t border-ink-line pt-3">
        <NavItem to="/account" label="My account" icon={User} />
      </div>
    </aside>
  );
}
