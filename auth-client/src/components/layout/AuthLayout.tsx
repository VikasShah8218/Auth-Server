import type { ReactNode } from "react";

/** The key profile cut along the top of the sign-in card (decorative). */
const TEETH = [28, 12, 20, 28, 12, 16, 12, 28, 22, 12, 18, 28];

export function AuthLayout({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-dvh place-items-center bg-ink px-4 py-6">
      <div className="w-full max-w-[400px]">
        <div className="overflow-hidden rounded-panel bg-surface shadow-modal">
          <div aria-hidden className="animate-cut flex h-10 items-end gap-1 bg-surface-2 px-7">
            {TEETH.map((height, i) => (
              <span
                key={i}
                className="w-full rounded-t-[3px]"
                style={{
                  height,
                  animationDelay: `${i * 40}ms`,
                  background: height > 12 ? "var(--accent)" : "var(--line-strong)",
                }}
              />
            ))}
          </div>
          <div className="grid gap-[18px] px-7 pt-[26px] pb-7">{children}</div>
        </div>
        {footer && <p className="mt-[18px] text-center text-xs text-ink-muted">{footer}</p>}
      </div>
    </div>
  );
}
