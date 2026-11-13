import type { UseQueryResult } from "@tanstack/react-query";
import { Monitor, MonitorOff, Smartphone } from "lucide-react";

import type { Schemas } from "@/api/client";
import { ListRow, Tile } from "@/components/common/ListRow";
import { EmptyState, ErrorState } from "@/components/common/States";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { amrLabel, deviceLabel, formatRelative, formatShortDate } from "@/lib/format";

type Session = Schemas["SessionOut"];

export function SessionList({
  query,
  onEnd,
  ending,
  endLabel = "End session",
}: {
  query: UseQueryResult<Session[]>;
  onEnd: (session: Session) => void;
  ending?: string | null;
  endLabel?: string;
}) {
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (query.isPending) {
    return (
      <div className="grid gap-3 p-[18px]">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }
  if (query.data.length === 0) {
    return (
      <EmptyState
        icon={MonitorOff}
        title="No live sessions"
        description="Nobody is signed in with this account right now."
      />
    );
  }
  return (
    <div>
      {query.data.map((session) => {
        const device = deviceLabel(session.user_agent);
        return (
          <ListRow
            key={session.id}
            leading={<Tile>{device.mobile ? <Smartphone /> : <Monitor />}</Tile>}
            title={
              <>
                {device.label}
                {session.current && (
                  <span className="text-xs font-normal text-accent-strong">This device</span>
                )}
              </>
            }
            meta={
              <>
                {session.ip && <span className="font-mono">{session.ip}</span>}
                {session.ip && " · "}
                {amrLabel(session.amr)} · signed in {formatRelative(session.auth_time)} · ends{" "}
                {formatShortDate(session.expires_at)}
              </>
            }
            action={
              !session.current && (
                <Button
                  variant="danger-ghost"
                  size="sm"
                  loading={ending === session.id}
                  onClick={() => onEnd(session)}
                >
                  {endLabel}
                </Button>
              )
            }
          />
        );
      })}
    </div>
  );
}
