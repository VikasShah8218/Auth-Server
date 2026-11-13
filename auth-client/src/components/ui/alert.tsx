import { CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

const tones = {
  danger: { classes: "bg-danger-soft text-danger", icon: TriangleAlert },
  warn: { classes: "bg-warn-soft text-warn", icon: TriangleAlert },
  info: { classes: "bg-info-soft text-info", icon: Info },
  ok: { classes: "bg-ok-soft text-ok", icon: CircleCheck },
};

export function Alert({
  tone = "info",
  children,
  className,
}: {
  tone?: keyof typeof tones;
  children: ReactNode;
  className?: string;
}) {
  const { classes, icon: Icon } = tones[tone];
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-2.5 rounded-control px-3 py-2.5 text-[13px] leading-[1.45]",
        classes,
        className,
      )}
    >
      <Icon className="mt-px size-4 shrink-0" aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
