import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Crumb = { label: string; to?: string };

type PageMeta = { crumbs: Crumb[]; setCrumbs: (crumbs: Crumb[]) => void };

const PageMetaContext = createContext<PageMeta | null>(null);

export function PageMetaProvider({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbs] = useState<Crumb[]>([]);
  return <PageMetaContext.Provider value={{ crumbs, setCrumbs }}>{children}</PageMetaContext.Provider>;
}

export function useCrumbs(): Crumb[] {
  return useContext(PageMetaContext)?.crumbs ?? [];
}

/** Sets the top bar's breadcrumb and the browser tab title. The last crumb names the page. */
export function usePageMeta(...crumbs: Crumb[]) {
  const context = useContext(PageMetaContext);
  const signature = crumbs.map((c) => `${c.label}|${c.to ?? ""}`).join("/");

  useEffect(() => {
    context?.setCrumbs(crumbs);
    const title = crumbs.length ? crumbs[crumbs.length - 1].label : "";
    document.title = title ? `${title} · Auth Server` : "Auth Server";
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the signature captures the crumbs' content
  }, [signature]);
}
