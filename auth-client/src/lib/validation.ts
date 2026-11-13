/** Zod rules that mirror the server's, so most mistakes are caught before a request. */
import { z } from "zod";

export const MIN_PASSWORD = 12;

export const username = z
  .string()
  .trim()
  .toLowerCase()
  .regex(/^[a-z0-9][a-z0-9._-]{2,63}$/, "3–64 characters: letters, numbers, dot, dash or underscore.");

export const appKey = z
  .string()
  .trim()
  .toUpperCase()
  .regex(/^[A-Z][A-Z0-9_]{1,31}$/, "2–32 characters: letters, numbers and _, starting with a letter.");

export const permissionCode = z
  .string()
  .trim()
  .toLowerCase()
  .regex(/^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$/, "Lower-case words joined by dots, e.g. vehicle.read.");

export const clientId = z
  .string()
  .trim()
  .regex(
    /^[a-z0-9][a-z0-9._-]{2,127}$/,
    "3–128 characters: lower-case letters, numbers, dot, dash or underscore.",
  );

export const optionalEmail = z
  .string()
  .trim()
  .toLowerCase()
  .refine((v) => v === "" || z.email().safeParse(v).success, "Enter a valid email address.");

export const personName = z.string().trim().max(64, "Use at most 64 characters.");

/** The server also refuses passwords that contain the username. */
export function passwordFor(usernameValue: () => string) {
  return z
    .string()
    .min(MIN_PASSWORD, `Use at least ${MIN_PASSWORD} characters.`)
    .max(256)
    .refine((v) => {
      const name = usernameValue().trim().toLowerCase();
      return !name || !v.toLowerCase().includes(name);
    }, "Don't include the username in the password.");
}

/** "" -> null, so optional fields are sent as empty. */
export const blankToNull = (value: string): string | null => (value.trim() === "" ? null : value.trim());
