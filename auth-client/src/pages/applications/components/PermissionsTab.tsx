import { zodResolver } from "@hookform/resolvers/zod";
import { Archive, Ellipsis, KeyRound, Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  useCreatePermission,
  usePermissions,
  useRetirePermission,
  useUpdatePermission,
} from "@/api/applications";
import type { Schemas } from "@/api/client";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { DataTable } from "@/components/common/DataTable";
import { FormField } from "@/components/common/FormField";
import { KeyCut } from "@/components/common/KeyCut";
import { EmptyState, ErrorState } from "@/components/common/States";
import { Alert } from "@/components/ui/alert";
import { Badge, Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogBody, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Checkbox, Input } from "@/components/ui/input";
import { ApiError, userMessage } from "@/lib/errors";
import { formatDate } from "@/lib/format";
import { blankToNull, permissionCode } from "@/lib/validation";

type Permission = Schemas["PermissionOut"];

function PermissionDialog({
  appKey,
  permission,
  open,
  onOpenChange,
}: {
  appKey: string;
  permission?: Permission;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreatePermission(appKey);
  const update = useUpdatePermission(appKey);
  const mutation = permission ? update : create;
  const schema = z.object({ code: permissionCode, description: z.string().trim().max(2000) });
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (open) form.reset({ code: permission?.code ?? "", description: permission?.description ?? "" });
    else mutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when opened
  }, [open]);

  const submit = form.handleSubmit((values) => {
    const done = (message: string) => () => {
      toast.success(message);
      onOpenChange(false);
    };
    if (permission) {
      update.mutate(
        { id: permission.id, description: blankToNull(values.description) },
        { onSuccess: done("Changes saved") },
      );
    } else {
      create.mutate(
        { code: values.code, description: blankToNull(values.description) },
        {
          onSuccess: (created) => {
            toast.success(`Permission created on bit ${created.bit}`);
            onOpenChange(false);
          },
          onError: (error) => {
            if (error instanceof ApiError && error.code === "permission_exists")
              form.setError("code", { message: "This permission already exists." });
          },
        },
      );
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} noValidate>
          <DialogBody
            icon={<KeyRound />}
            tone="accent"
            title={permission ? `Edit ${permission.code}` : "New permission"}
            description={
              permission
                ? "The code and bit are permanent. Only the description can change."
                : "It gets the next free bit, which is never reused. Recreating a retired code brings back its old bit."
            }
          >
            {mutation.error &&
              !(mutation.error instanceof ApiError && mutation.error.code === "permission_exists") && (
                <Alert tone="danger">{userMessage(mutation.error)}</Alert>
              )}
            <div className="mt-1 grid gap-4">
              {!permission && (
                <FormField
                  label="Code"
                  help="For example vehicle.read."
                  error={form.formState.errors.code?.message}
                >
                  <Input
                    autoFocus
                    className="font-mono"
                    autoCapitalize="none"
                    spellCheck={false}
                    {...form.register("code")}
                  />
                </FormField>
              )}
              <FormField
                label="Description"
                help="Optional. Shown to administrators."
                error={form.formState.errors.description?.message}
              >
                <Input autoFocus={!!permission} {...form.register("description")} />
              </FormField>
            </div>
          </DialogBody>
          <DialogFooter>
            <DialogClose asChild>
              <Button>Cancel</Button>
            </DialogClose>
            <Button type="submit" variant="primary" loading={mutation.isPending}>
              {permission ? "Save changes" : "Create permission"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function PermissionsTab({ appKey }: { appKey: string }) {
  const [showRetired, setShowRetired] = useState(false);
  const permissions = usePermissions(appKey, showRetired);
  const map = usePermissions(appKey, true);
  const retire = useRetirePermission(appKey);
  const [dialog, setDialog] = useState<{ permission?: Permission } | null>(null);
  const [retiring, setRetiring] = useState<Permission | null>(null);

  return (
    <div className="grid gap-4">
      {map.data && map.data.length > 0 && (
        <Card>
          <CardHeader
            title="Bit map"
            description="Every bit this application has used. Retired bits stay reserved."
          />
          <CardBody>
            <KeyCut
              label={`Permission map. ${map.data.filter((p) => !p.retired_at).length} live bits, ${map.data.filter((p) => p.retired_at).length} retired`}
              bits={map.data.map((p) => ({
                code: p.code,
                bit: p.bit,
                retired: !!p.retired_at,
                held: !p.retired_at,
              }))}
              meta={`${map.data.filter((p) => !p.retired_at).length} live · ${map.data.filter((p) => p.retired_at).length} retired · limit 1,024`}
            />
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Permissions"
          description="Codes that tokens carry as bits. Give them to roles on the Roles tab."
          actions={
            <>
              <label className="hidden cursor-pointer items-center gap-2 text-[13px] text-fg-2 sm:flex">
                <Checkbox checked={showRetired} onChange={(event) => setShowRetired(event.target.checked)} />
                Show retired
              </label>
              <Button size="sm" variant="primary" onClick={() => setDialog({})}>
                <Plus />
                New permission
              </Button>
            </>
          }
        />
        {permissions.isError ? (
          <ErrorState error={permissions.error} onRetry={() => permissions.refetch()} />
        ) : (
          <DataTable<Permission>
            caption="Permissions"
            loading={permissions.isPending}
            rows={permissions.data}
            rowKey={(p) => String(p.id)}
            empty={
              <EmptyState
                icon={KeyRound}
                title="No permissions"
                description="Create the first permission for this application."
              />
            }
            columns={[
              { key: "bit", header: "Bit", numeric: true, cell: (p) => p.bit },
              {
                key: "code",
                header: "Code",
                primary: true,
                cell: (p) => (
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip>{p.code}</Chip>
                    {p.bit === 0 && <span className="text-xs text-muted">Full access</span>}
                  </div>
                ),
              },
              {
                key: "description",
                header: "Description",
                cell: (p) => <span className="text-fg-2">{p.description || "—"}</span>,
              },
              {
                key: "status",
                header: "Status",
                cell: (p) =>
                  p.retired_at ? (
                    <Badge>Retired {formatDate(p.retired_at)}</Badge>
                  ) : (
                    <Badge tone="ok" dot>
                      Live
                    </Badge>
                  ),
              },
              {
                key: "actions",
                header: <span className="sr-only">Actions</span>,
                actions: true,
                cell: (p) =>
                  p.bit === 0 ? null : (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${p.code}`}>
                          <Ellipsis />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent>
                        <DropdownMenuItem onSelect={() => setDialog({ permission: p })}>
                          <Pencil />
                          Edit description
                        </DropdownMenuItem>
                        {!p.retired_at && (
                          <DropdownMenuItem tone="danger" onSelect={() => setRetiring(p)}>
                            <Archive />
                            Retire permission
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ),
              },
            ]}
          />
        )}
      </Card>

      <PermissionDialog
        appKey={appKey}
        permission={dialog?.permission}
        open={dialog !== null}
        onOpenChange={(open) => !open && setDialog(null)}
      />
      <ConfirmDialog
        open={retiring !== null}
        onOpenChange={(open) => !open && setRetiring(null)}
        icon={<Archive />}
        title={`Retire ${retiring?.code}?`}
        description={`It's removed from every role, and tokens of the people who held it stop working within seconds. Bit ${retiring?.bit} stays reserved, so it is never reused.`}
        confirmLabel="Retire permission"
        pending={retire.isPending}
        error={retire.error}
        onConfirm={() =>
          retiring &&
          retire.mutate(retiring.id, {
            onSuccess: () => {
              setRetiring(null);
              toast.success("Permission retired");
            },
          })
        }
      />
    </div>
  );
}
