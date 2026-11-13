import { X } from "lucide-react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/cn";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  className,
  children,
  wide = false,
  ...props
}: ComponentProps<typeof DialogPrimitive.Content> & { wide?: boolean }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[rgba(10,13,24,0.55)]" />
      <DialogPrimitive.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 max-h-[calc(100vh-32px)] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-card border border-line bg-surface text-fg shadow-modal outline-none",
          wide ? "max-w-[560px]" : "max-w-[440px]",
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute top-3 right-3 grid size-8 cursor-pointer place-items-center rounded-control text-muted hover:bg-surface-2 hover:text-fg"
          aria-label="Close"
        >
          <X className="size-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogBody({
  icon,
  title,
  description,
  children,
  tone = "neutral",
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  tone?: "neutral" | "danger" | "accent";
}) {
  return (
    <div className="grid gap-2.5 px-[22px] pt-[22px] pb-[18px]">
      {icon && (
        <span
          className={cn(
            "grid size-10 place-items-center rounded-[10px] [&_svg]:size-5",
            tone === "danger" && "bg-danger-soft text-danger",
            tone === "accent" && "bg-accent-soft text-accent-strong",
            tone === "neutral" && "bg-surface-2 text-fg-2",
          )}
        >
          {icon}
        </span>
      )}
      <DialogPrimitive.Title className="pr-8 font-display text-lg font-bold">{title}</DialogPrimitive.Title>
      {description ? (
        <DialogPrimitive.Description className="text-fg-2">{description}</DialogPrimitive.Description>
      ) : (
        <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
      )}
      {children}
    </div>
  );
}

export function DialogFooter({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex flex-wrap justify-end gap-2 rounded-b-card border-t border-line bg-surface-2 px-[22px] py-3.5",
        className,
      )}
      {...props}
    />
  );
}
