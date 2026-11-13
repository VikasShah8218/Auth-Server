import { AppWindow, Plus } from "lucide-react";
import { useState } from "react";

import type { Schemas } from "@/api/client";
import { heldSummary, KeyCut } from "@/components/common/KeyCut";
import { EmptyState } from "@/components/common/States";
import { Badge, Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";

import { EditRolesDialog } from "./EditRolesDialog";

type User = Schemas["UserDetail"];

/** The user's access per application: roles, the key-cut strip of permission bits, and the codes held. */
export function AccessTab({ user }: { user: User }) {
  const [editing, setEditing] = useState<{ appKey?: string } | null>(null);
  const heldKeys = user.applications.map((a) => a.app_key);

  return (
    <div className="grid gap-4">
      {user.applications.length === 0 ? (
        <Card>
          <EmptyState
            icon={AppWindow}
            title="No access yet"
            description={`${user.username} can sign in to this console only. Give a role in an application to grant access there.`}
            action={
              <Button size="sm" variant="primary" onClick={() => setEditing({})}>
                <Plus />
                Give access to an application
              </Button>
            }
          />
        </Card>
      ) : (
        user.applications.map((app) => (
          <Card key={app.app_key}>
            <CardHeader
              leading={<Chip>{app.app_key}</Chip>}
              title={app.app_name}
              description={`${app.roles.map((r) => r.name).join(", ")} · ${heldSummary(app.bits)}`}
              actions={
                <Button size="sm" onClick={() => setEditing({ appKey: app.app_key })}>
                  Edit roles
                </Button>
              }
            />
            <CardBody className="grid grid-cols-1 items-start gap-5 md:grid-cols-[auto_minmax(0,1fr)] md:gap-8">
              <div className="min-w-0">
                <div className="mb-[22px] text-xs text-muted">Access key</div>
                <KeyCut
                  bits={app.bits}
                  meta={
                    <span>
                      <b className="font-medium text-fg-2">{app.bits.filter((b) => b.held).length}</b> of{" "}
                      {app.bits.length} bits
                    </span>
                  }
                />
              </div>
              <div className="grid gap-4">
                <div className="grid gap-1.5">
                  <span className="text-[13px] font-medium">Roles</span>
                  <div className="flex flex-wrap gap-1">
                    {app.roles.map((role) => (
                      <Badge key={role.id} tone="accent">
                        {role.name}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div className="grid gap-1.5">
                  <span className="text-[13px] font-medium">Permissions</span>
                  {app.permissions.length ? (
                    <div className="flex flex-wrap gap-1">
                      {app.permissions.map((code) => (
                        <Chip key={code}>{code === "*" ? "* (full access)" : code}</Chip>
                      ))}
                    </div>
                  ) : (
                    <span className="text-[13px] text-muted">These roles grant no permissions yet.</span>
                  )}
                </div>
              </div>
            </CardBody>
          </Card>
        ))
      )}

      {user.applications.length > 0 && (
        <Button className="justify-self-start" onClick={() => setEditing({})}>
          <Plus />
          Give access to another application
        </Button>
      )}

      <EditRolesDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        user={user}
        appKey={editing?.appKey}
        exclude={editing?.appKey ? [] : heldKeys}
      />
    </div>
  );
}
