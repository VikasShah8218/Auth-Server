import { zodResolver } from "@hookform/resolvers/zod";
import { Ellipsis, Pencil, Plus, Trash2, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  useCreateRole,
  useDeleteRole,
  usePermissions,
  useRole,
  useRoles,
  useSetRolePermissions,
  useUpdateRole,
} from "@/api/applications";
import type { Schemas } from "@/api/client";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { DataTable } from "@/components/common/DataTable";
import { FormField } from "@/components/common/FormField";
import { EmptyState, ErrorState } from "@/components/common/States";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Dialog, DialogBody, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Checkbox, Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, userMessage } from "@/lib/errors";
import { blankToNull } from "@/lib/validation";

type Role = Schemas["RoleOut"];

const schema = z.object({
  name: z.string().trim().min(1, "Give the role a name.").max(64),
  description: z.string().trim().max(2000),
});

/** Creates a role, or edits one: its name, description and permissions in one dialog. */
function RoleDialog({
  appKey,
  role,
  open,
  onOpenChange,
}: {
  appKey: string;
  role?: Role;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreateRole(appKey);
  const update = useUpdateRole(appKey);
  const setPermissions = useSetRolePermissions(appKey);
  const permissions = usePermissions(appKey);
  const detail = useRole(appKey, open && role ? role.id : null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const isAdmin = role?.name === "Admin";

  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (open) {
      form.reset({ name: role?.name ?? "", description: role?.description ?? "" });
      setError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when opened
  }, [open]);

  useEffect(() => {
    setSelected(new Set(detail.data?.permissions.map((p) => p.id) ?? []));
  }, [detail.data]);

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const submit = form.handleSubmit(async (values) => {
    setError(null);
    setSaving(true);
    try {
      const body = { name: values.name, description: blankToNull(values.description) };
      const saved = role
        ? await update.mutateAsync({
            id: role.id,
            description: body.description,
            ...(isAdmin || body.name === role.name ? {} : { name: body.name }),
          })
        : await create.mutateAsync(body);
      const before = new Set(detail.data?.permissions.map((p) => p.id) ?? []);
      const changed = selected.size !== before.size || [...selected].some((id) => !before.has(id));
      if (changed) await setPermissions.mutateAsync({ id: saved.id, permissionIds: [...selected] });
      toast.success(role ? "Role saved" : "Role created", {
        description: changed
          ? "Members' tokens for this application are refreshed within seconds."
          : undefined,
      });
      onOpenChange(false);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "role_exists") {
        form.setError("name", { message: "A role with this name already exists." });
      } else {
        setError(caught);
      }
    } finally {
      setSaving(false);
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide>
        <form onSubmit={submit} noValidate>
          <DialogBody
            icon={<UsersRound />}
            tone="accent"
            title={role ? `Edit ${role.name}` : "New role"}
            description="A role is a named set of permissions. People get roles, never single permissions."
          >
            {error ? <Alert tone="danger">{userMessage(error)}</Alert> : null}
            <div className="mt-1 grid gap-4">
              <FormField
                label="Name"
                help={isAdmin ? "The Admin role can't be renamed." : undefined}
                error={form.formState.errors.name?.message}
              >
                <Input autoFocus readOnly={isAdmin} {...form.register("name")} />
              </FormField>
              <FormField
                label="Description"
                help="Optional."
                error={form.formState.errors.description?.message}
              >
                <Input {...form.register("description")} />
              </FormField>
              <fieldset className="m-0 grid gap-1 border-0 p-0">
                <legend className="mb-1.5 text-[13px] font-medium">Permissions</legend>
                {permissions.isPending || (role && detail.isPending) ? (
                  <Skeleton className="h-24 w-full" />
                ) : (
                  <div className="grid max-h-64 gap-0.5 overflow-y-auto rounded-control border border-line p-1">
                    {permissions.data?.map((p) => (
                      <label
                        key={p.id}
                        className="flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 hover:bg-surface-2"
                      >
                        <Checkbox
                          className="mt-0.5"
                          checked={selected.has(p.id)}
                          onChange={() => toggle(p.id)}
                        />
                        <span className="min-w-0">
                          <span className="font-mono text-[13px]">{p.code}</span>
                          <span className="ml-2 font-mono text-[11px] text-muted">bit {p.bit}</span>
                          {(p.description || p.bit === 0) && (
                            <span className="block text-xs text-muted">
                              {p.bit === 0 ? "Full access" : p.description}
                            </span>
                          )}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </fieldset>
            </div>
          </DialogBody>
          <DialogFooter>
            <DialogClose asChild>
              <Button>Cancel</Button>
            </DialogClose>
            <Button type="submit" variant="primary" loading={saving}>
              {role ? "Save role" : "Create role"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function RolesTab({ appKey }: { appKey: string }) {
  const roles = useRoles(appKey);
  const remove = useDeleteRole(appKey);
  const [dialog, setDialog] = useState<{ role?: Role } | null>(null);
  const [deleting, setDeleting] = useState<Role | null>(null);

  return (
    <Card>
      <CardHeader
        title="Roles"
        description="Changing a role's permissions refreshes its members' access everywhere within seconds."
        actions={
          <Button size="sm" variant="primary" onClick={() => setDialog({})}>
            <Plus />
            New role
          </Button>
        }
      />
      {roles.isError ? (
        <ErrorState error={roles.error} onRetry={() => roles.refetch()} />
      ) : (
        <DataTable<Role>
          caption="Roles"
          loading={roles.isPending}
          rows={roles.data}
          rowKey={(r) => String(r.id)}
          empty={
            <EmptyState
              icon={UsersRound}
              title="No roles"
              description="Create a role and choose its permissions."
            />
          }
          columns={[
            {
              key: "name",
              header: "Role",
              primary: true,
              cell: (r) => (
                <button
                  type="button"
                  className="cursor-pointer border-0 bg-transparent p-0 text-left font-medium text-fg hover:underline"
                  onClick={() => setDialog({ role: r })}
                >
                  {r.name}
                  {r.name === "Admin" && (
                    <Badge tone="accent" className="ml-2">
                      Full access
                    </Badge>
                  )}
                </button>
              ),
            },
            {
              key: "description",
              header: "Description",
              cell: (r) => <span className="text-fg-2">{r.description || "—"}</span>,
            },
            {
              key: "actions",
              header: <span className="sr-only">Actions</span>,
              actions: true,
              cell: (r) => (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${r.name}`}>
                      <Ellipsis />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem onSelect={() => setDialog({ role: r })}>
                      <Pencil />
                      Edit role
                    </DropdownMenuItem>
                    {r.name !== "Admin" && (
                      <DropdownMenuItem tone="danger" onSelect={() => setDeleting(r)}>
                        <Trash2 />
                        Delete role
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              ),
            },
          ]}
        />
      )}

      <RoleDialog
        appKey={appKey}
        role={dialog?.role}
        open={dialog !== null}
        onOpenChange={(open) => !open && setDialog(null)}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        icon={<Trash2 />}
        title={`Delete ${deleting?.name}?`}
        description="Everyone who holds it loses its permissions in this application within seconds."
        confirmLabel="Delete role"
        pending={remove.isPending}
        error={remove.error}
        onConfirm={() =>
          deleting &&
          remove.mutate(deleting.id, {
            onSuccess: () => {
              setDeleting(null);
              toast.success("Role deleted");
            },
          })
        }
      />
    </Card>
  );
}
