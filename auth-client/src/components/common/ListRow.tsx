import type { ReactNode } from "react";

/** A row in a card's list: sessions, factors, activity. */
export function ListRow({
  leading,
  title,
  meta,
  action,
}: {
  leading?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3.5 border-t border-line px-[18px] py-3.5 first:border-t-0 sm:flex-nowrap">
      {leading}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 font-medium">{title}</div>
        {meta && <div className="mt-0.5 text-[12.5px] text-muted">{meta}</div>}
      </div>
      {action && <div className="ml-[50px] shrink-0 sm:ml-0">{action}</div>}
    </div>
  );
}

/** Square icon tile used as a ListRow's leading element. */
export function Tile({ children }: { children: ReactNode }) {
  return (
    <span className="grid size-9 shrink-0 place-items-center rounded-[9px] bg-surface-2 text-fg-2 [&_svg]:size-4">
      {children}
    </span>
  );
}
