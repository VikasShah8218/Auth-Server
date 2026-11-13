import { Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Toaster } from "sonner";

import { PageMetaProvider } from "./page-meta";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

/** Sidebar + top bar + page. Below 1024px the sidebar is a drawer. */
export function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  // The drawer belongs to the page it was opened on, so any navigation closes it.
  const [openedOn, setOpenedOn] = useState<string | null>(null);
  const navOpen = openedOn === pathname;
  const close = () => setOpenedOn(null);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpenedOn(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  return (
    <PageMetaProvider>
      <a
        href="#main"
        className="sr-only z-50 rounded-control bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <div className="grid min-h-dvh grid-cols-1 lg:grid-cols-[248px_minmax(0,1fr)]">
        <Sidebar open={navOpen} />
        {navOpen && (
          <button
            type="button"
            aria-label="Close navigation"
            className="fixed inset-0 z-30 cursor-default border-0 bg-[rgba(10,13,24,0.5)] lg:hidden"
            onClick={close}
          />
        )}
        <div className="flex min-w-0 flex-col">
          <Topbar onMenu={() => setOpenedOn(pathname)} />
          <main id="main" className="mx-auto w-full max-w-[1200px] px-4 pt-5 pb-12 md:px-6 md:pt-7 md:pb-14">
            <Outlet />
          </main>
        </div>
      </div>
      {/* Toasts live with the signed-in app, so the login page every app's users load stays small. */}
      <Toaster
        position="bottom-right"
        toastOptions={{
          classNames: {
            toast: "rounded-control! border! border-line! bg-surface! text-fg! shadow-pop! font-sans!",
            description: "text-fg-2!",
          },
        }}
      />
    </PageMetaProvider>
  );
}
