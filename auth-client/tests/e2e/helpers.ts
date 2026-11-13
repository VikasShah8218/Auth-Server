import { createHmac } from "node:crypto";

import { expect, type Page } from "@playwright/test";

export const ADMIN = { username: "e2e.admin", password: "e2e-admin-password-1" };

/** Signs in through the real flow: /bff/login -> /oauth/authorize -> /login -> back to the console. */
export async function signIn(page: Page, username: string, password: string) {
  await page.goto("/");
  await page.waitForURL(/\/login\?/);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function signInAsAdmin(page: Page) {
  await signIn(page, ADMIN.username, ADMIN.password);
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
}

/** RFC 6238 TOTP from a base32 secret: what an authenticator app would show. */
export function totp(secret: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret.replace(/=+$/, "").toUpperCase())
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((byte) => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const hmac = createHmac("sha1", key).update(counter).digest();
  const offset = hmac[hmac.length - 1] & 0xf;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return code.toString().padStart(6, "0");
}

export const unique = (prefix: string) => `${prefix}${Date.now().toString(36).slice(-5)}`;
