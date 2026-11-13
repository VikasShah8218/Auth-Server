import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import type { Schemas } from "@/api/client";
import { useResetPassword, useUpdateUser } from "@/api/users";
import { FormField } from "@/components/common/FormField";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardFooter, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, userMessage } from "@/lib/errors";
import { formatDate } from "@/lib/format";
import { blankToNull, optionalEmail, passwordFor, personName } from "@/lib/validation";

type User = Schemas["UserDetail"];

const profileSchema = z.object({ first_name: personName, last_name: personName, email: optionalEmail });
type ProfileValues = z.infer<typeof profileSchema>;

function ProfileForm({ user }: { user: User }) {
  const update = useUpdateUser(user.public_id);
  const values = {
    first_name: user.first_name ?? "",
    last_name: user.last_name ?? "",
    email: user.email ?? "",
  };
  const form = useForm<ProfileValues>({ resolver: zodResolver(profileSchema), defaultValues: values });
  const errors = form.formState.errors;

  const submit = form.handleSubmit((v) =>
    update.mutate(
      {
        first_name: blankToNull(v.first_name),
        last_name: blankToNull(v.last_name),
        email: blankToNull(v.email),
      },
      {
        onSuccess: () => toast.success("Changes saved"),
        onError: (error) => {
          if (error instanceof ApiError && error.code === "user_exists") {
            form.setError("email", { message: "This email is already in use." });
          }
        },
      },
    ),
  );

  return (
    <Card>
      <form onSubmit={submit} noValidate>
        <CardHeader title="Profile" />
        <CardBody className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {update.error && !(update.error instanceof ApiError && update.error.code === "user_exists") && (
            <Alert tone="danger" className="sm:col-span-2">
              {userMessage(update.error)}
            </Alert>
          )}
          <FormField label="First name" error={errors.first_name?.message}>
            <Input {...form.register("first_name")} />
          </FormField>
          <FormField label="Last name" error={errors.last_name?.message}>
            <Input {...form.register("last_name")} />
          </FormField>
          <FormField label="Email" error={errors.email?.message}>
            <Input type="email" {...form.register("email")} />
          </FormField>
          <FormField label="Username" help="Usernames can't be changed.">
            <Input className="font-mono" value={user.username} readOnly />
          </FormField>
        </CardBody>
        <CardFooter>
          <span>
            Created {formatDate(user.created_at)} · updated {formatDate(user.updated_at)}
          </span>
          <Button
            type="submit"
            variant="primary"
            loading={update.isPending}
            disabled={!form.formState.isDirty}
          >
            Save changes
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

function PasswordForm({ user }: { user: User }) {
  const reset = useResetPassword(user.public_id);
  const schema = z.object({ password: passwordFor(() => user.username) });
  const form = useForm<{ password: string }>({
    resolver: zodResolver(schema),
    defaultValues: { password: "" },
  });

  const submit = form.handleSubmit(({ password }) =>
    reset.mutate(password, {
      onSuccess: () => {
        form.reset();
        toast.success("Password set", { description: `${user.username} was signed out everywhere.` });
      },
    }),
  );

  return (
    <Card>
      <form onSubmit={submit} noValidate>
        <CardHeader
          title="Set a new password"
          description={`${user.first_name || user.username} is signed out everywhere and uses the new password next time.`}
        />
        <CardBody className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {reset.error && (
            <Alert tone="danger" className="sm:col-span-2">
              {userMessage(reset.error)}
            </Alert>
          )}
          <FormField label="New password" error={form.formState.errors.password?.message}>
            <Input type="password" autoComplete="new-password" {...form.register("password")} />
          </FormField>
        </CardBody>
        <CardFooter>
          <span>At least 12 characters, and not containing the username.</span>
          <Button type="submit" loading={reset.isPending}>
            Set password
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

export function ProfileTab({ user }: { user: User }) {
  return (
    <div className="grid gap-4">
      {/* Remounts after a save, so the form shows what the server stored. */}
      <ProfileForm key={user.updated_at} user={user} />
      <PasswordForm user={user} />
    </div>
  );
}
