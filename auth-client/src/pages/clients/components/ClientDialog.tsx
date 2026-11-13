import { zodResolver } from "@hookform/resolvers/zod";
import { Plug } from "lucide-react";
import { useEffect } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { useApplicationOptions } from "@/api/applications";
import type { Schemas } from "@/api/client";
import { useCreateClient, useUpdateClient } from "@/api/clients";
import { FormField } from "@/components/common/FormField";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Checkbox, Input, Select, Textarea } from "@/components/ui/input";
import { ApiError, userMessage } from "@/lib/errors";
import { clientId } from "@/lib/validation";

type Client = Schemas["ClientOut"];

const BROWSER_SCOPES = [
  { value: "openid", help: "Sign-in identity (ID token)" },
  { value: "profile", help: "Username and name" },
  { value: "email", help: "Email address" },
];
const SERVICE_SCOPES = [
  { value: "events.read", help: "Follow the revocation event stream" },
  { value: "permissions.read", help: "Read the permission map" },
  { value: "users.read", help: "Reserved for user lookups" },
];

function redirectUriError(uri: string): string | null {
  try {
    const url = new URL(uri);
    const local = url.hostname === "localhost" || url.hostname === "127.0.0.1";
    if (url.protocol !== "https:" && !(url.protocol === "http:" && local))
      return `${uri}: use https, or http on localhost.`;
    if (url.hash) return `${uri}: remove the # part.`;
    return null;
  } catch {
    return `${uri}: not a valid URL.`;
  }
}

const schema = z
  .object({
    client_id: clientId,
    name: z.string().trim().min(1, "Give the client a name.").max(128),
    app_key: z.string().min(1, "Choose the application."),
    type: z.enum(["public", "confidential"]),
    redirect_uris: z.string(),
    scopes: z.array(z.string()),
    audiences: z.array(z.string()),
  })
  .superRefine((v, ctx) => {
    const uris = v.redirect_uris.split(/\s+/).filter(Boolean);
    const bad = uris.map(redirectUriError).find(Boolean);
    if (bad) ctx.addIssue({ code: "custom", path: ["redirect_uris"], message: bad });
    if (v.type === "public" && uris.length === 0)
      ctx.addIssue({
        code: "custom",
        path: ["redirect_uris"],
        message: "A browser app needs at least one redirect URI.",
      });
  });
type Values = z.infer<typeof schema>;

/** Creates a client, or edits one (its id, application and type never change). */
export function ClientDialog({
  open,
  onOpenChange,
  client,
  defaultApp,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  client?: Client;
  defaultApp?: string;
  onCreated?: (result: Schemas["ClientWithSecret"]) => void;
}) {
  const apps = useApplicationOptions();
  const create = useCreateClient();
  const update = useUpdateClient(client?.client_id ?? "");
  const mutation = client ? update : create;

  const initial = (): Values => ({
    client_id: client?.client_id ?? "",
    name: client?.name ?? "",
    app_key: client?.app_key ?? defaultApp ?? "",
    type: (client?.type as Values["type"]) ?? "confidential",
    redirect_uris: client?.redirect_uris.join("\n") ?? "",
    scopes: client?.scopes ?? ["events.read", "permissions.read"],
    audiences: client?.audiences ?? [],
  });
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: initial() });
  const errors = form.formState.errors;
  const type = form.watch("type");
  const appKey = form.watch("app_key");

  useEffect(() => {
    if (open) form.reset(initial());
    else mutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when opened
  }, [open]);

  // Switching type changes which scopes make sense.
  useEffect(() => {
    if (client || !form.formState.dirtyFields.type) return;
    form.setValue(
      "scopes",
      type === "public" ? ["openid", "profile", "email"] : ["events.read", "permissions.read"],
    );
    if (type === "public") form.setValue("audiences", []);
  }, [type]); // eslint-disable-line react-hooks/exhaustive-deps

  const scopes = type === "public" ? BROWSER_SCOPES : [...SERVICE_SCOPES, ...BROWSER_SCOPES];
  const audienceChoices = apps.data?.filter((a) => a.key !== "AUTH" && a.key !== appKey) ?? [];

  const submit = form.handleSubmit((v) => {
    const redirectUris = v.redirect_uris.split(/\s+/).filter(Boolean);
    if (client) {
      update.mutate(
        { name: v.name, redirect_uris: redirectUris, scopes: v.scopes, audiences: v.audiences },
        { onSuccess: () => onOpenChange(false) },
      );
    } else {
      create.mutate(
        { ...v, redirect_uris: redirectUris },
        {
          onSuccess: (result) => {
            onOpenChange(false);
            onCreated?.(result);
          },
          onError: (error) => {
            if (error instanceof ApiError && error.code === "client_exists")
              form.setError("client_id", { message: "A client with this ID already exists." });
          },
        },
      );
    }
  });

  const checkboxes = (name: "scopes" | "audiences", options: { value: string; help: string }[]) => (
    <Controller
      control={form.control}
      name={name}
      render={({ field }) => (
        <div className="grid gap-0.5 rounded-control border border-line p-1">
          {options.map((option) => (
            <label
              key={option.value}
              className="flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 hover:bg-surface-2"
            >
              <Checkbox
                className="mt-0.5"
                checked={field.value.includes(option.value)}
                onChange={(event) =>
                  field.onChange(
                    event.target.checked
                      ? [...field.value, option.value]
                      : field.value.filter((x) => x !== option.value),
                  )
                }
              />
              <span>
                <span className="font-mono text-[13px]">{option.value}</span>
                <span className="block text-xs text-muted">{option.help}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    />
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide>
        <form onSubmit={submit} noValidate>
          <DialogBody
            icon={<Plug />}
            tone="accent"
            title={client ? `Edit ${client.client_id}` : "New client"}
            description={
              client
                ? "Reducing scopes or audiences ends the client's current tokens everywhere."
                : "A server (confidential) gets a secret, shown once. A browser app (public) signs users in with PKCE."
            }
          >
            {mutation.error &&
              !(mutation.error instanceof ApiError && mutation.error.code === "client_exists") && (
                <Alert tone="danger">{userMessage(mutation.error)}</Alert>
              )}
            <div className="mt-1 grid grid-cols-1 gap-4 sm:grid-cols-2">
              {!client && (
                <>
                  <FormField label="Client ID" help="For example anpr-api." error={errors.client_id?.message}>
                    <Input
                      autoFocus
                      className="font-mono"
                      autoCapitalize="none"
                      spellCheck={false}
                      {...form.register("client_id")}
                    />
                  </FormField>
                  <FormField label="Application" error={errors.app_key?.message}>
                    <Select {...form.register("app_key")}>
                      <option value="">Choose…</option>
                      {apps.data?.map((a) => (
                        <option key={a.key} value={a.key}>
                          {a.key} · {a.name}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                  <FormField label="Type" className="sm:col-span-2">
                    <Select {...form.register("type")}>
                      <option value="confidential">Server (confidential, gets a secret)</option>
                      <option value="public">Browser app (public, PKCE sign-in)</option>
                    </Select>
                  </FormField>
                </>
              )}
              <FormField label="Name" error={errors.name?.message} className="sm:col-span-2">
                <Input autoFocus={!!client} {...form.register("name")} />
              </FormField>
              <FormField
                label="Redirect URIs"
                help={
                  type === "public"
                    ? "One per line. Must match exactly."
                    : "Only needed if this server also signs users in."
                }
                error={errors.redirect_uris?.message}
                className="sm:col-span-2"
              >
                <Textarea
                  rows={2}
                  className="font-mono text-[13px]"
                  spellCheck={false}
                  {...form.register("redirect_uris")}
                />
              </FormField>
              <div className="grid gap-1.5">
                <span className="text-[13px] font-medium">Scopes</span>
                {checkboxes("scopes", scopes)}
              </div>
              {type === "confidential" && (
                <div className="grid content-start gap-1.5">
                  <span className="text-[13px] font-medium">Audiences</span>
                  {audienceChoices.length ? (
                    checkboxes(
                      "audiences",
                      audienceChoices.map((a) => ({
                        value: a.key,
                        help: `Call ${a.name} or act for its users`,
                      })),
                    )
                  ) : (
                    <p className="text-xs text-muted">No other applications to call.</p>
                  )}
                </div>
              )}
            </div>
          </DialogBody>
          <DialogFooter>
            <DialogClose asChild>
              <Button>Cancel</Button>
            </DialogClose>
            <Button type="submit" variant="primary" loading={mutation.isPending}>
              {client ? "Save changes" : "Create client"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
