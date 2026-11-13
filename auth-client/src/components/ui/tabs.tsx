import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/cn";

export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn("mb-5 flex gap-1 overflow-x-auto border-b border-line", className)}
      {...props}
    />
  );
}

export function TabsTrigger({
  className,
  count,
  children,
  ...props
}: ComponentProps<typeof TabsPrimitive.Trigger> & { count?: ReactNode }) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "-mb-px inline-flex cursor-pointer items-center gap-2 border-b-2 border-transparent px-3 py-2.5 text-[13.5px] font-medium whitespace-nowrap text-muted hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg",
        className,
      )}
      {...props}
    >
      {children}
      {count !== undefined && (
        <span className="rounded bg-surface-2 px-1.5 py-px font-mono text-[11px] font-medium text-fg-2">
          {count}
        </span>
      )}
    </TabsPrimitive.Trigger>
  );
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn("outline-none", className)} {...props} />;
}
