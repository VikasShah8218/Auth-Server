import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from "react";

import { Label } from "@/components/ui/input";
import { cn } from "@/lib/cn";

/**
 * Label + control + help or error. The control gets its id, aria-invalid and aria-describedby wired up.
 */
export function FormField({
  label,
  help,
  error,
  children,
  className,
  aside,
}: {
  label: ReactNode;
  help?: ReactNode;
  error?: string;
  children: ReactElement<Record<string, unknown>>;
  className?: string;
  aside?: ReactNode;
}) {
  const id = useId();
  const describedBy = error || help ? `${id}-note` : undefined;
  const control = isValidElement(children)
    ? cloneElement(children, {
        id: (children.props.id as string | undefined) ?? id,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": describedBy,
      })
    : children;

  return (
    <div className={cn("grid gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <Label htmlFor={(children.props.id as string | undefined) ?? id}>{label}</Label>
        {aside}
      </div>
      {control}
      {error ? (
        <span id={describedBy} className="text-xs text-danger">
          {error}
        </span>
      ) : help ? (
        <span id={describedBy} className="text-xs text-muted">
          {help}
        </span>
      ) : null}
    </div>
  );
}
