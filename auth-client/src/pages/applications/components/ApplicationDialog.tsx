import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { AppWindow } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useCreateApplication, useUpdateApplication } from "@/api/applications";
import type { Schemas } from "@/api/client";
import { FormField } from "@/components/common/FormField";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { ApiError, userMessage } from "@/lib/errors";
import { appKey, blankToNull } from "@/lib/validation";

const schema = z.object({
  key: appKey,
  name: z.string().trim().min(1, "Give the application a name.").max(128),
  description: z.string().trim().max(2000),
});
type Values = z.infer<typeof schema>;

/** Creates an application, or edits its name and description (the key never changes). */
export function ApplicationDialog({
  open,
  onOpenChange,
  app,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  app?: Schemas["ApplicationOut"];
}) {
  const navigate = useNavigate();
  const create = useCreateApplication();
  const update = useUpdateApplication(app?.key ?? "");
  const mutation = app ? update : create;

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { key: app?.key ?? "", name: app?.name ?? "", description: app?.description ?? "" },
  });
  const errors = form.formState.errors;

  useEffect(() => {
    if (open) form.reset({ key: app?.key ?? "", name: app?.name ?? "", description: app?.description ?? "" });
    else mutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when opened
  }, [open]);

  const submit = form.handleSubmit((values) => {
    if (app) {
      update.mutate(
        { name: values.name, description: blankToNull(values.description) },
        {
          onSuccess: () => {
            toast.success("Changes saved");
            onOpenChange(false);
          },
        },
      );
      return;
    }
    create.mutate(
      { key: values.key, name: values.name, description: blankToNull(values.description) },
      {
        onSuccess: (created) => {
          toast.success("Application created", {
            description: "It starts with the * permission and an Admin role.",
          });
          onOpenChange(false);
          navigate({ to: "/applications/$key", params: { key: created.key } });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === "application_exists") {
            form.setError("key", { message: "An application with this key already exists." });
          }
        },
      },
    );
  });

  const knownError = mutation.error instanceof ApiError && mutation.error.code === "application_exists";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} noValidate>
          <DialogBody
            icon={<AppWindow />}
            tone="accent"
            title={app ? `Edit ${app.key}` : "New application"}
            description={
              app
                ? "The key is permanent because tokens carry it."
                : "The key is permanent: tokens carry it as their audience. It starts with a * permission and an Admin role."
            }
          >
            {mutation.error && !knownError && <Alert tone="danger">{userMessage(mutation.error)}</Alert>}
            <div className="mt-1 grid gap-4">
              {!app && (
                <FormField
                  label="Key"
                  help="For example ANPR. Letters, numbers and _."
                  error={errors.key?.message}
                >
                  <Input
                    autoFocus
                    className="font-mono uppercase"
                    autoCapitalize="characters"
                    {...form.register("key")}
                  />
                </FormField>
              )}
              <FormField label="Name" error={errors.name?.message}>
                <Input autoFocus={!!app} {...form.register("name")} />
              </FormField>
              <FormField label="Description" help="Optional." error={errors.description?.message}>
                <Textarea rows={3} {...form.register("description")} />
              </FormField>
            </div>
          </DialogBody>
          <DialogFooter>
            <DialogClose asChild>
              <Button>Cancel</Button>
            </DialogClose>
            <Button type="submit" variant="primary" loading={mutation.isPending}>
              {app ? "Save changes" : "Create application"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
