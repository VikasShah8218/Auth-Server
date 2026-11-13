import { KeyRound } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { useApplicationOptions, useRoles } from "@/api/applications";
import type { Schemas } from "@/api/client";
import { useSetUserRoles } from "@/api/users";
import { FormField } from "@/components/common/FormField";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Checkbox, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { userMessage } from "@/lib/errors";

/**
 * Sets a user's roles in one application. With appKey it edits that app; without, it first asks which app
 * (excluding the ones the user already has a role in).
 */
export function EditRolesDialog({
  open,
  onOpenChange,
  user,
  appKey,
  exclude = [],
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: Schemas["UserDetail"];
  appKey?: string;
  exclude?: string[];
}) {
  const apps = useApplicationOptions();
  const [chosenApp, setChosenApp] = useState("");
  const key = appKey ?? chosenApp;
  const roles = useRoles(key);
  const setRoles = useSetUserRoles(user.public_id);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const current = user.applications.find((a) => a.app_key === key);
  useEffect(() => {
    if (!open) return;
    setSelected(new Set(current?.roles.map((r) => r.id) ?? []));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the dialog opens or the app changes
  }, [open, key]);

  useEffect(() => {
    if (!open) {
      setChosenApp("");
      setRoles.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset on close only
  }, [open]);

  const choices = apps.data?.filter((a) => a.is_active && !exclude.includes(a.key)) ?? [];

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function save() {
    setRoles.mutate(
      { app_key: key, role_ids: [...selected] },
      {
        onSuccess: () => {
          toast.success(selected.size ? "Roles saved" : "Access removed", {
            description: "Existing tokens for this application stop working within seconds.",
          });
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogBody
          icon={<KeyRound />}
          tone="accent"
          title={appKey ? `Roles in ${appKey}` : "Give access to an application"}
          description={`Choose ${user.username}'s roles. Removing every role removes access to the application.`}
        >
          {!appKey && (
            <FormField label="Application">
              <Select value={chosenApp} onChange={(event) => setChosenApp(event.target.value)}>
                <option value="">Choose an application</option>
                {choices.map((app) => (
                  <option key={app.key} value={app.key}>
                    {app.key} · {app.name}
                  </option>
                ))}
              </Select>
            </FormField>
          )}

          {key && (
            <fieldset className="m-0 grid gap-1 border-0 p-0">
              <legend className="mb-1.5 text-[13px] font-medium">Roles</legend>
              {roles.isPending ? (
                <Skeleton className="h-20 w-full" />
              ) : roles.isError ? (
                <Alert tone="danger">{userMessage(roles.error)}</Alert>
              ) : roles.data.length === 0 ? (
                <p className="text-[13px] text-muted">
                  This application has no roles yet. Create one on its page.
                </p>
              ) : (
                roles.data.map((role) => (
                  <label
                    key={role.id}
                    className="flex cursor-pointer items-start gap-2.5 rounded-control px-2 py-2 hover:bg-surface-2"
                  >
                    <Checkbox
                      className="mt-0.5"
                      checked={selected.has(role.id)}
                      onChange={() => toggle(role.id)}
                    />
                    <span>
                      <span className="font-medium">{role.name}</span>
                      {role.description && (
                        <span className="block text-xs text-muted">{role.description}</span>
                      )}
                    </span>
                  </label>
                ))
              )}
            </fieldset>
          )}

          {setRoles.error && <Alert tone="danger">{userMessage(setRoles.error)}</Alert>}
        </DialogBody>
        <DialogFooter>
          <DialogClose asChild>
            <Button>Cancel</Button>
          </DialogClose>
          <Button
            variant="primary"
            onClick={save}
            loading={setRoles.isPending}
            disabled={!key || (!appKey && selected.size === 0)}
          >
            Save roles
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
