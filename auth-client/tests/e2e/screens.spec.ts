/**
 * Screenshots of the main screens for visual review against ui-design/. Opt-in:
 *
 *   SCREENS_DIR=./screens AUTH_PYTHON=... npx playwright test screens
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { signIn, signInAsAdmin } from "./helpers";

const dir = process.env.SCREENS_DIR;
test.skip(!dir, "Set SCREENS_DIR to take screenshots");
test.describe.configure({ mode: "serial" });

async function api(request: APIRequestContext, method: string, path: string, data?: unknown) {
  const session = await (await request.get("/bff/session")).json();
  const response = await request.fetch(path, {
    method,
    data,
    headers: { "x-csrf-token": session.csrf_token, "content-type": "application/json" },
  });
  if (!response.ok() && response.status() !== 409)
    throw new Error(`${method} ${path}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}

async function seed(page: Page) {
  const r = page.request;
  await api(r, "POST", "/v1/admin/applications", { key: "ANPR", name: "Number plate recognition" });
  await api(r, "POST", "/v1/admin/applications", { key: "SNVR", name: "Shah NVR" });
  const codes = [
    "vehicle.read",
    "vehicle.write",
    "camera.read",
    "report.view",
    "report.export",
    "watchlist.edit",
    "alpr.legacy",
    "settings.edit",
  ];
  const perms = [];
  for (const code of codes)
    perms.push(await api(r, "POST", "/v1/admin/applications/ANPR/permissions", { code }));
  const legacy = perms.find((p) => p?.code === "alpr.legacy");
  if (legacy) await api(r, "DELETE", `/v1/admin/applications/ANPR/permissions/${legacy.id}`);
  const role = await api(r, "POST", "/v1/admin/applications/ANPR/roles", {
    name: "Operator",
    description: "Day-to-day gate work",
  });
  if (role) {
    const held = perms.filter(
      (p) => p && ["vehicle.read", "vehicle.write", "camera.read", "report.view"].includes(p.code),
    );
    await api(r, "PUT", `/v1/admin/applications/ANPR/roles/${role.id}/permissions`, {
      permission_ids: held.map((p) => p.id),
    });
  }
  const people = [
    ["imran.k", "Imran", "Khan", "imran.khan@example.com", true],
    ["neha.sharma", "Neha", "Sharma", "neha.sharma@example.com", true],
    ["rahul.verma", "Rahul", "Verma", "rahul.verma@example.com", false],
    ["gate2.operator", "Gate 2", "shift desk", null, true],
  ] as const;
  for (const [username, first, last, email, active] of people) {
    const user = await api(r, "POST", "/v1/admin/users", {
      username,
      first_name: first,
      last_name: last,
      email,
      password: "a-long-enough-pass-1",
      is_active: active,
    });
    if (user && role)
      await api(r, "PUT", `/v1/admin/users/${user.public_id}/roles`, {
        app_key: "ANPR",
        role_ids: [role.id],
      });
  }
}

async function shot(page: Page, name: string) {
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true });
}

test("login", async ({ page }) => {
  await page.goto("/login");
  await page.waitForTimeout(800);
  await shot(page, "01-login");
});

test("console screens", async ({ page }) => {
  test.setTimeout(120_000);
  await signInAsAdmin(page);
  await seed(page);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  await shot(page, "02-dashboard");

  await page.goto("/users");
  await expect(page.getByRole("link", { name: "imran.k" })).toBeVisible();
  await shot(page, "03-users");

  await page.getByRole("link", { name: "imran.k" }).click();
  await expect(page.getByRole("list", { name: /Access key/ })).toBeVisible();
  await shot(page, "04-user-detail");

  await page.goto("/applications/ANPR");
  await expect(page.getByRole("heading", { name: "Number plate recognition", level: 1 })).toBeVisible();
  await shot(page, "05-application");

  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/users");
  await expect(page.getByRole("link", { name: "imran.k" })).toBeVisible();
  await shot(page, "06-users-dark");
  await page.goto("/account?tab=security");
  await shot(page, "07-account-dark");

  await page.emulateMedia({ colorScheme: "light" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/users");
  await expect(page.getByRole("link", { name: "imran.k" })).toBeVisible();
  await shot(page, "08-users-phone");
});

test("mfa step", async ({ page }) => {
  // gate2.operator has no MFA; show the code step layout via a fresh admin sign-in is not possible, so use login error state.
  await signIn(page, "imran.k", "wrong-password-here");
  await expect(page.getByRole("alert")).toBeVisible();
  await shot(page, "09-login-error");
});
