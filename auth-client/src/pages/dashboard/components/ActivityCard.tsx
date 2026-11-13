import { Link } from "@tanstack/react-router";
import { ChevronRight, ScrollText, TriangleAlert } from "lucide-react";

import { useAudit } from "@/api/operations";
import { ListRow } from "@/components/common/ListRow";
import { EmptyState, ErrorState } from "@/components/common/States";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { auditLabel, isAlarming } from "@/lib/audit";
import { formatRelative, initials } from "@/lib/format";

export function ActivityCard() {
  const audit = useAudit({ offset: 0 }, 5);

  return (
    <Card>
      <CardHeader
        title="Recent activity"
        actions={
          <Button asChild variant="ghost" size="sm">
            <Link to="/audit">
              Audit log
              <ChevronRight />
            </Link>
          </Button>
        }
      />
      {audit.isError ? (
        <ErrorState error={audit.error} onRetry={() => audit.refetch()} />
      ) : audit.isPending ? (
        <div className="grid gap-3 p-[18px]">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : audit.data.items.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title="Nothing yet"
          description="Changes to access appear here as they happen."
        />
      ) : (
        <div>
          {audit.data.items.map((item) => (
            <ListRow
              key={item.id}
              leading={
                isAlarming(item.action) ? (
                  <Avatar muted>
                    <TriangleAlert />
                  </Avatar>
                ) : (
                  <Avatar muted={item.actor.startsWith("system:") || item.actor_name === item.actor}>
                    {initials(item.actor_name)}
                  </Avatar>
                )
              }
              title={auditLabel(item.action)}
              meta={[item.actor_name, item.app, formatRelative(item.created_at)].filter(Boolean).join(" · ")}
            />
          ))}
        </div>
      )}
    </Card>
  );
}
