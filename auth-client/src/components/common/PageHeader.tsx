import type { ReactNode } from "react";

/** One per page: optional eyebrow (a true fact about the page, e.g. an id), title, description, actions. */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  leading,
  children,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  leading?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 items-center gap-4">
        {leading}
        <div className="min-w-0">
          {eyebrow && (
            <div className="mb-1.5 font-mono text-[11.5px] font-medium tracking-[0.04em] break-all text-accent-strong">
              {eyebrow}
            </div>
          )}
          <h1 className="text-[26px] leading-tight font-bold">{title}</h1>
          {description && <p className="mt-1.5 text-fg-2">{description}</p>}
          {children}
        </div>
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
