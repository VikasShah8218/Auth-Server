import * as Menu from "@radix-ui/react-dropdown-menu";
import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;

export function DropdownMenuContent({
  className,
  align = "end",
  sideOffset = 6,
  ...props
}: ComponentProps<typeof Menu.Content>) {
  return (
    <Menu.Portal>
      <Menu.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "z-50 min-w-[210px] rounded-menu border border-line bg-surface p-1.5 text-fg shadow-pop outline-none",
          className,
        )}
        {...props}
      />
    </Menu.Portal>
  );
}

export function DropdownMenuItem({
  className,
  tone = "default",
  ...props
}: ComponentProps<typeof Menu.Item> & { tone?: "default" | "danger" }) {
  return (
    <Menu.Item
      className={cn(
        "flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4",
        tone === "danger"
          ? "text-danger data-[highlighted]:bg-danger-soft"
          : "text-fg data-[highlighted]:bg-surface-2",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuSeparator({ className, ...props }: ComponentProps<typeof Menu.Separator>) {
  return <Menu.Separator className={cn("my-1.5 h-px bg-line", className)} {...props} />;
}

export function DropdownMenuHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-1.5 border-b border-line px-2.5 pt-2 pb-2.5">
      <strong className="block text-[13.5px]">{title}</strong>
      {subtitle && <span className="text-xs text-muted">{subtitle}</span>}
    </div>
  );
}
