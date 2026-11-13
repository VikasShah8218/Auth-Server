import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronRight, Menu, Search } from "lucide-react";
import { useEffect, useRef, type FormEvent } from "react";

import { useSession } from "@/api/session";
import { Button } from "@/components/ui/button";

import { useCrumbs } from "./page-meta";
import { ThemeToggle } from "./ThemeToggle";
import { UserMenu } from "./UserMenu";

/** Finds users from anywhere: Enter opens the users list filtered by the text. "/" focuses it. */
function QuickSearch() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (event.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(target.tagName) && !target.isContentEditable) {
        event.preventDefault();
        input.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    const q = input.current?.value.trim();
    if (q) navigate({ to: "/users", search: { q } });
  }

  return (
    <form
      onSubmit={submit}
      className="hidden h-[34px] w-[280px] items-center gap-2 rounded-control border border-line bg-surface px-2.5 text-muted focus-within:border-accent focus-within:shadow-[var(--focus-ring)] md:flex"
    >
      <Search className="size-4 shrink-0" aria-hidden />
      <label htmlFor="quick-search" className="sr-only">
        Search users
      </label>
      <input
        ref={input}
        id="quick-search"
        placeholder="Search users by name or email"
        className="w-full min-w-0 border-0 bg-transparent text-fg outline-none focus:shadow-none"
      />
      <kbd className="rounded border border-line px-[5px] py-px font-mono text-[11px] text-muted">/</kbd>
    </form>
  );
}

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const crumbs = useCrumbs();
  const session = useSession();

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-bg px-4 md:px-6">
      <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={onMenu}>
        <Menu />
      </Button>
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[13px] text-muted">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <span key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-1.5">
              {index > 0 && <ChevronRight className="size-3.5 shrink-0" aria-hidden />}
              {last || !crumb.to ? (
                <span
                  aria-current={last ? "page" : undefined}
                  className={last ? "truncate font-medium text-fg" : ""}
                >
                  {crumb.label}
                </span>
              ) : (
                <Link to={crumb.to} className="no-underline hover:text-fg">
                  {crumb.label}
                </Link>
              )}
            </span>
          );
        })}
      </nav>
      <div className="flex-1" />
      {session.is_admin && <QuickSearch />}
      <ThemeToggle />
      <UserMenu />
    </header>
  );
}
