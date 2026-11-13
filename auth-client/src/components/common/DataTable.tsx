import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";

export type Column<T> = {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Label shown beside the value when the table becomes cards on a phone. Defaults to the header. */
  label?: string;
  align?: "left" | "right";
  /** Monospace numbers. */
  numeric?: boolean;
  /** The row's main cell: shown first on a phone, without a label. */
  primary?: boolean;
  /** The row's actions: top right on a phone. */
  actions?: boolean;
  className?: string;
};

/**
 * Server-paged table. Paging and filters live outside (TableToolbar, Pagination); this only renders rows,
 * a loading skeleton, and the empty state. Below 720px each row becomes a card.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  empty,
  skeletonRows = 5,
  caption,
}: {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  loading?: boolean;
  empty?: ReactNode;
  skeletonRows?: number;
  caption?: string;
}) {
  if (!loading && rows && rows.length === 0 && empty) return <>{empty}</>;

  return (
    <div className="overflow-x-auto">
      <table className="table-cards w-full border-collapse text-[13.5px]">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  "border-b border-line bg-surface-2 px-4 py-2.5 text-left text-xs font-medium whitespace-nowrap text-muted",
                  (column.align === "right" || column.numeric) && "text-right",
                  column.actions && "w-px",
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading || !rows
            ? Array.from({ length: skeletonRows }, (_, i) => (
                <tr key={i}>
                  {columns.map((column) => (
                    <td key={column.key} className="border-b border-line px-4 py-3.5">
                      <Skeleton className={cn("h-4", column.primary ? "w-40" : "w-16")} />
                    </td>
                  ))}
                </tr>
              ))
            : rows.map((row) => (
                <tr key={rowKey(row)} className="group">
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      data-label={column.label ?? (typeof column.header === "string" ? column.header : "")}
                      data-primary={column.primary || undefined}
                      data-actions={column.actions || undefined}
                      className={cn(
                        "border-b border-line px-4 py-3 align-middle group-last:border-b-0 group-hover:bg-surface-2",
                        (column.align === "right" || column.numeric) && "text-right",
                        column.numeric && "font-mono text-[12.5px]",
                        column.actions && "w-px text-right whitespace-nowrap",
                        column.className,
                      )}
                    >
                      {column.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}

/** Filters above a table. */
export function TableToolbar({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap gap-2.5 border-b border-line p-3 [&_select]:h-9 [&_select]:w-auto [&_select]:min-w-[150px]">
      {children}
    </div>
  );
}
