import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { startConsoleLogin } from "@/api/client";
import { sessionQuery, type ConsoleSession } from "@/api/session";
import { ErrorState } from "@/components/common/States";
import { Skeleton } from "@/components/ui/skeleton";
import {
  validateAuditSearch,
  validateClientsSearch,
  validateLoginSearch,
  validatePageSearch,
  validateTabSearch,
  validateUsersSearch,
} from "@/lib/search";
import NotFound from "@/pages/errors/NotFound";

export type RouterContext = { queryClient: QueryClient };

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
  notFoundComponent: NotFound,
});

// Public: the hosted login page for this console and every connected app.
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: validateLoginSearch,
  component: lazyRouteComponent(() => import("@/pages/auth/Login")),
});

// Signed in: everything below needs a console session.
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "_app",
  beforeLoad: async ({ context }): Promise<{ session: ConsoleSession }> => {
    const session = await context.queryClient.ensureQueryData(sessionQuery);
    if (!session) {
      startConsoleLogin();
      // The browser is leaving for the sign-in; never render the app meanwhile.
      await new Promise(() => {});
    }
    return { session: session as ConsoleSession };
  },
  component: lazyRouteComponent(() => import("@/components/layout/AppShell"), "AppShell"),
});

const accountRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/account",
  validateSearch: validateTabSearch,
  component: lazyRouteComponent(() => import("@/pages/account/MyAccount")),
});

// Administrators only. Anyone else goes to their own account page.
const adminRoute = createRoute({
  getParentRoute: () => appRoute,
  id: "_admin",
  beforeLoad: ({ context }) => {
    if (!context.session.is_admin) throw redirect({ to: "/account" });
  },
});

const admin = <P extends string>(path: P) => ({ getParentRoute: () => adminRoute, path }) as const;

const dashboardRoute = createRoute({
  ...admin("/"),
  component: lazyRouteComponent(() => import("@/pages/dashboard/Dashboard")),
});
const applicationsRoute = createRoute({
  ...admin("/applications"),
  validateSearch: validatePageSearch,
  component: lazyRouteComponent(() => import("@/pages/applications/ApplicationsList")),
});
const applicationRoute = createRoute({
  ...admin("/applications/$key"),
  validateSearch: validateTabSearch,
  component: lazyRouteComponent(() => import("@/pages/applications/ApplicationDetail")),
});
const usersRoute = createRoute({
  ...admin("/users"),
  validateSearch: validateUsersSearch,
  component: lazyRouteComponent(() => import("@/pages/users/UsersList")),
});
const userRoute = createRoute({
  ...admin("/users/$id"),
  validateSearch: validateTabSearch,
  component: lazyRouteComponent(() => import("@/pages/users/UserDetail")),
});
const clientsRoute = createRoute({
  ...admin("/clients"),
  validateSearch: validateClientsSearch,
  component: lazyRouteComponent(() => import("@/pages/clients/ClientsList")),
});
const clientRoute = createRoute({
  ...admin("/clients/$clientId"),
  component: lazyRouteComponent(() => import("@/pages/clients/ClientDetail")),
});
const keysRoute = createRoute({
  ...admin("/keys"),
  component: lazyRouteComponent(() => import("@/pages/keys/SigningKeys")),
});
const downstreamRoute = createRoute({
  ...admin("/downstream"),
  component: lazyRouteComponent(() => import("@/pages/downstream/DownstreamSync")),
});
const auditRoute = createRoute({
  ...admin("/audit"),
  validateSearch: validateAuditSearch,
  component: lazyRouteComponent(() => import("@/pages/audit/AuditLog")),
});

// Development only: every component in every state, for comparison with ui-design/. Never in production builds.
const devRoutes = import.meta.env.DEV
  ? [
      createRoute({
        getParentRoute: () => rootRoute,
        path: "/dev/components",
        component: lazyRouteComponent(() => import("@/pages/dev/Components")),
      }),
    ]
  : [];

const routeTree = rootRoute.addChildren([
  loginRoute,
  appRoute.addChildren([
    accountRoute,
    adminRoute.addChildren([
      dashboardRoute,
      applicationsRoute,
      applicationRoute,
      usersRoute,
      userRoute,
      clientsRoute,
      clientRoute,
      keysRoute,
      downstreamRoute,
      auditRoute,
    ]),
  ]),
  ...devRoutes,
]);

function PagePending() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-80" />
      <Skeleton className="h-64 w-full rounded-card" />
    </div>
  );
}

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0,
    defaultPendingComponent: PagePending,
    defaultPendingMs: 150,
    defaultErrorComponent: ({ error, reset }) => <ErrorState error={error} onRetry={reset} />,
    scrollRestoration: true,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
