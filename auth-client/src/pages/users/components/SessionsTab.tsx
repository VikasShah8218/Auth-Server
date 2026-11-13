import type { UseQueryResult } from "@tanstack/react-query";
import { toast } from "sonner";

import type { Schemas } from "@/api/client";
import { useEndSession } from "@/api/users";
import { SessionList } from "@/components/common/SessionList";
import { Card, CardHeader } from "@/components/ui/card";
import { userMessage } from "@/lib/errors";

type Session = Schemas["SessionOut"];

export function SessionsTab({
  userId,
  name,
  query,
}: {
  userId: string;
  name: string;
  query: UseQueryResult<Session[]>;
}) {
  const end = useEndSession(userId);

  return (
    <Card>
      <CardHeader
        title="Live sessions"
        description={`Ending a session signs ${name} out on that device. Connected apps reject its tokens within seconds.`}
      />
      <SessionList
        query={query}
        ending={end.isPending ? (end.variables ?? null) : null}
        onEnd={(session) =>
          end.mutate(session.id, {
            onSuccess: () => toast.success("Session ended"),
            onError: (error) => toast.error(userMessage(error)),
          })
        }
      />
    </Card>
  );
}
