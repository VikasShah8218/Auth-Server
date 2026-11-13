import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

const sizes = {
  sm: "size-7 text-[11px]",
  md: "size-8 text-xs",
  lg: "size-14 text-[19px]",
};

export function Avatar({
  children,
  size = "md",
  muted = false,
  className,
}: {
  children: ReactNode;
  size?: keyof typeof sizes;
  muted?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-display font-semibold [&_svg]:size-4",
        muted ? "bg-surface-2 text-muted" : "bg-accent-soft text-accent-strong",
        sizes[size],
        className,
      )}
    >
      {children}
    </span>
  );
}
