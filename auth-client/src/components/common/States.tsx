import { RefreshCw, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { userMessage } from "@/lib/errors";

/** An empty screen is an invitation to act. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="grid justify-items-center gap-2 px-6 py-12 text-center">
      <div className="mb-1 grid size-11 place-items-center rounded-xl bg-surface-2 text-muted">
        <Icon className="size-5" aria-hidden />
      </div>
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {description && <p className="max-w-[340px] text-[13px] text-muted">{description}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/** What went wrong, and a way to try again. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <EmptyState
      icon={TriangleAlert}
      title="This couldn't be loaded"
      description={userMessage(error)}
      action={
        onRetry && (
          <Button size="sm" onClick={onRetry}>
            <RefreshCw aria-hidden />
            Try again
          </Button>
        )
      }
    />
  );
}
