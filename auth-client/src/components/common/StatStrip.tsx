import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/format";

export type Stat = { label: string; icon: LucideIcon; value: number | undefined; note?: ReactNode };

export function StatStrip({ stats, loading }: { stats: Stat[]; loading?: boolean }) {
  return (
    <section
      aria-label="Totals"
      className="mb-4 grid grid-cols-2 rounded-card border border-line bg-surface shadow-soft md:grid-cols-4"
    >
      {stats.map(({ label, icon: Icon, value, note }, index) => (
        <div
          key={label}
          className={[
            "px-[18px] py-4",
            index % 2 === 1 ? "border-l border-line" : "",
            index >= 2 ? "border-t border-line md:border-t-0" : "",
            index === 2 ? "md:border-l" : "",
          ].join(" ")}
        >
          <div className="flex items-center gap-1.5 text-[12.5px] text-muted">
            <Icon className="size-4" aria-hidden />
            {label}
          </div>
          {loading ? (
            <Skeleton className="mt-2 mb-1 h-7 w-16" />
          ) : (
            <div className="mt-0.5 font-display text-[28px] font-bold tracking-[-0.02em]">
              {formatNumber(value)}
            </div>
          )}
          <div className="min-h-[18px] text-xs text-fg-2">{loading ? null : note}</div>
        </div>
      ))}
    </section>
  );
}
