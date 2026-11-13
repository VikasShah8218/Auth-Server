import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

export const fieldControl =
  "w-full rounded-control border border-line-strong bg-surface px-3 text-fg outline-none transition-[border-color,box-shadow] focus:border-accent focus:shadow-[var(--focus-ring)] aria-invalid:border-danger read-only:bg-surface-2 read-only:text-fg-2 disabled:opacity-60";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(fieldControl, "h-[38px]", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={cn(fieldControl, "min-h-20 py-2", className)} {...props} />;
}

/** Native select with the design's chevron: small, accessible, works on phones. */
export function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(fieldControl, "select-chevron h-[38px] cursor-pointer pr-8", className)}
      {...props}
    />
  );
}

export function Checkbox({ className, ...props }: Omit<ComponentProps<"input">, "type">) {
  return (
    <input
      type="checkbox"
      className={cn("size-4 cursor-pointer accent-[var(--accent)]", className)}
      {...props}
    />
  );
}

export function Label({ className, ...props }: ComponentProps<"label">) {
  // Callers pass htmlFor (FormField always does), so the label is associated where it's used.
  // oxlint-disable-next-line jsx-a11y/label-has-associated-control
  return <label className={cn("text-[13px] font-medium text-fg", className)} {...props} />;
}
