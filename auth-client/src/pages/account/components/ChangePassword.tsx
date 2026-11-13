import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useChangePassword } from "@/api/account";
import { FormField } from "@/components/common/FormField";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardFooter, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, userMessage } from "@/lib/errors";
import { passwordFor } from "@/lib/validation";

export function ChangePassword({ username }: { username: string }) {
  const change = useChangePassword();
  const schema = z
    .object({
      current_password: z.string().min(1, "Enter your current password."),
      new_password: passwordFor(() => username),
      confirm: z.string(),
    })
    .refine((v) => v.new_password === v.confirm, {
      path: ["confirm"],
      message: "The passwords don't match.",
    });
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { current_password: "", new_password: "", confirm: "" },
  });
  const errors = form.formState.errors;

  const submit = form.handleSubmit((v) =>
    change.mutate(
      { current_password: v.current_password, new_password: v.new_password },
      {
        onSuccess: () => {
          form.reset();
          toast.success("Password changed", { description: "Your other devices were signed out." });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === "invalid_credentials")
            form.setError("current_password", { message: "Your current password is incorrect." });
        },
      },
    ),
  );

  const known = change.error instanceof ApiError && change.error.code === "invalid_credentials";

  return (
    <Card>
      <form onSubmit={submit} noValidate>
        <CardHeader
          title="Change password"
          description="Your other devices are signed out when you change it."
        />
        <CardBody className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {change.error && !known && (
            <Alert tone="danger" className="sm:col-span-2">
              {userMessage(change.error)}
            </Alert>
          )}
          <FormField
            label="Current password"
            error={errors.current_password?.message}
            className="sm:col-span-2 sm:max-w-[calc(50%-8px)]"
          >
            <Input type="password" autoComplete="current-password" {...form.register("current_password")} />
          </FormField>
          <FormField label="New password" error={errors.new_password?.message}>
            <Input type="password" autoComplete="new-password" {...form.register("new_password")} />
          </FormField>
          <FormField label="Repeat new password" error={errors.confirm?.message}>
            <Input type="password" autoComplete="new-password" {...form.register("confirm")} />
          </FormField>
        </CardBody>
        <CardFooter>
          <span>At least 12 characters, and not containing your username.</span>
          <Button type="submit" variant="primary" loading={change.isPending}>
            Change password
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
