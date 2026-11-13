import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

const badgeVariants = cva(
  "inline-flex h-[22px] items-center gap-1.5 rounded-full border px-2 text-xs leading-none font-medium whitespace-nowrap [&_svg]:size-3.5",
  {
    variants: {
      tone: {
        neutral: "border-line bg-surface-2 text-fg-2",
        ok: "border-transparent bg-ok-soft text-ok",
        warn: "border-transparent bg-warn-soft text-warn",
        danger: "border-transparent bg-danger-soft text-danger",
        info: "border-transparent bg-info-soft text-info",
        accent: "border-transparent bg-accent-soft text-accent-strong",
      },
      dot: { true: "before:size-1.5 before:rounded-full before:bg-current before:content-['']" },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeTone = NonNullable<VariantProps<typeof badgeVariants>["tone"]>;

export function Badge({
  className,
  tone,
  dot,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone, dot }), className)} {...props} />;
}

/** Small monospace tag for keys and codes: ANPR, vehicle.read. */
export function Chip({ className, ...props }: ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-[5px] border border-line bg-surface-2 px-1.5 font-mono text-[11.5px] font-medium text-fg-2",
        className,
      )}
      {...props}
    />
  );
}
