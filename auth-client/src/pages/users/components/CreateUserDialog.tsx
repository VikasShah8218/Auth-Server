import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { UserPlus } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useCreateUser } from "@/api/users";
import { FormField } from "@/components/common/FormField";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Checkbox, Input } from "@/components/ui/input";
import { ApiError, userMessage } from "@/lib/errors";
import { blankToNull, optionalEmail, passwordFor, personName, username } from "@/lib/validation";

const schema = z
  .object({
    username,
    first_name: personName,
    last_name: personName,
    email: optionalEmail,
    password: passwordFor(() => ""),
    is_active: z.boolean(),
  });
// TEMP: username-in-password check disabled
// .refine((v) => !v.username || !v.password.toLowerCase().includes(v.username.toLowerCase()), {
//   path: ["password"],
//   message: "Don't include the username in the password.",
// });
type Values = z.infer<typeof schema>;

export function CreateUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreateUser();
  const navigate = useNavigate();

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { username: "", first_name: "", last_name: "", email: "", password: "", is_active: true },
  });
  const errors = form.formState.errors;

  useEffect(() => {
    if (!open) {
      form.reset();
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset on close only
  }, [open]);

  const submit = form.handleSubmit((values) =>
    create.mutate(
      {
        username: values.username,
        password: values.password,
        email: blankToNull(values.email),
        first_name: blankToNull(values.first_name),
        last_name: blankToNull(values.last_name),
        is_active: values.is_active,
      },
      {
        onSuccess: (user) => {
          toast.success("User created", { description: "Give them roles in the applications they use." });
          onOpenChange(false);
          navigate({ to: "/users/$id", params: { id: user.public_id } });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === "user_exists") {
            form.setError("username", { message: "This username or email is already in use." });
          }
        },
      },
    ),
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide>
        <form onSubmit={submit} noValidate>
          <DialogBody
            icon={<UserPlus />}
            tone="accent"
            title="New user"
            description="They sign in with this username and password. Add MFA from their own account page."
          >
            {create.error && !(create.error instanceof ApiError && create.error.code === "user_exists") && (
              <Alert tone="danger">{userMessage(create.error)}</Alert>
            )}
            <div className="mt-1 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField label="Username" error={errors.username?.message} className="sm:col-span-2">
                <Input autoFocus autoCapitalize="none" spellCheck={false} {...form.register("username")} />
              </FormField>
              <FormField label="First name" error={errors.first_name?.message}>
                <Input autoComplete="off" {...form.register("first_name")} />
              </FormField>
              <FormField label="Last name" error={errors.last_name?.message}>
                <Input autoComplete="off" {...form.register("last_name")} />
              </FormField>
              <FormField
                label="Email"
                help="Optional."
                error={errors.email?.message}
                className="sm:col-span-2"
              >
                <Input type="email" autoComplete="off" {...form.register("email")} />
              </FormField>
              <FormField
                label="Password"
                help="At least 12 characters, not containing the username."
                error={errors.password?.message}
                className="sm:col-span-2"
              >
                <Input type="password" autoComplete="new-password" {...form.register("password")} />
              </FormField>
              <label className="flex cursor-pointer items-center gap-2 text-[13px] text-fg-2 sm:col-span-2">
                <Checkbox {...form.register("is_active")} />
                Active: the user can sign in now
              </label>
            </div>
          </DialogBody>
          <DialogFooter>
            <DialogClose asChild>
              <Button>Cancel</Button>
            </DialogClose>
            <Button type="submit" variant="primary" loading={create.isPending}>
              Create user
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
