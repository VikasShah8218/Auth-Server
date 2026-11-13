import { Link } from "@tanstack/react-router";
import { Users } from "lucide-react";

import { useMembers } from "@/api/applications";
import type { Schemas } from "@/api/client";
import { DataTable } from "@/components/common/DataTable";
import { EmptyState, ErrorState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { initials } from "@/lib/format";

type Member = Schemas["MemberOut"];

export function MembersTab({ appKey }: { appKey: string }) {
  const members = useMembers(appKey);

  return (
    <Card>
      <CardHeader
        title="Members"
        description="People holding at least one role here. Change roles on each user's page."
      />
      {members.isError ? (
        <ErrorState error={members.error} onRetry={() => members.refetch()} />
      ) : (
        <DataTable<Member>
          caption="Members"
          loading={members.isPending}
          rows={members.data}
          rowKey={(m) => m.public_id}
          empty={
            <EmptyState
              icon={Users}
              title="Nobody has access yet"
              description="Open a user and give them a role in this application."
            />
          }
          columns={[
            {
              key: "user",
              header: "User",
              primary: true,
              cell: (m) => (
                <div className="flex items-center gap-2.5">
                  <Avatar muted={!m.is_active}>{initials(m.username)}</Avatar>
                  <Link
                    to="/users/$id"
                    params={{ id: m.public_id }}
                    className="font-medium no-underline hover:underline"
                  >
                    {m.username}
                  </Link>
                </div>
              ),
            },
            {
              key: "roles",
              header: "Roles",
              cell: (m) => (
                <div className="flex flex-wrap justify-end gap-1 md:justify-start">
                  {m.roles.map((r) => (
                    <Badge key={r.id} tone="accent">
                      {r.name}
                    </Badge>
                  ))}
                </div>
              ),
            },
            {
              key: "status",
              header: "Status",
              cell: (m) => <StatusBadge status={m.is_active ? "active" : "disabled"} />,
            },
          ]}
        />
      )}
    </Card>
  );
}
