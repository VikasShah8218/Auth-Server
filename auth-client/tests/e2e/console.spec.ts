import { expect, test } from "@playwright/test";

import { ADMIN, signIn, signInAsAdmin, totp, unique } from "./helpers";

test.describe.configure({ mode: "serial" });

test("a wrong password is refused with a clear message", async ({ page }) => {
  await signIn(page, ADMIN.username, "not-the-password");
  await expect(page.getByRole("alert")).toContainText("Incorrect username or password");
  await expect(page).toHaveURL(/\/login/);
});

test("a bad return_to never leaves the site", async ({ page }) => {
  await page.goto("/login?return_to=https://evil.example/oauth/authorize?x=1");
  await page.getByLabel("Username").fill(ADMIN.username);
  await page.getByLabel("Password", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Falls back to the console's own sign-in, which ends at the dashboard on this origin.
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  expect(new URL(page.url()).origin).toBe("http://localhost:5182");
});

test("an admin builds an application and gives a user access", async ({ page }) => {
  const key = unique("E2E").toUpperCase();
  const username = unique("alice.");

  await signInAsAdmin(page);

  // Application with two permissions and a role holding one of them.
  await page.getByRole("link", { name: "Applications" }).click();
  await page.getByRole("button", { name: "New application" }).click();
  await page.getByLabel("Key", { exact: true }).fill(key);
  await page.getByLabel("Name", { exact: true }).fill("End to end");
  await page.getByRole("button", { name: "Create application" }).click();
  await expect(page.getByRole("heading", { name: "End to end", level: 1 })).toBeVisible();

  for (const code of ["vehicle.read", "vehicle.write"]) {
    await page.getByRole("button", { name: "New permission" }).click();
    await page.getByLabel("Code", { exact: true }).fill(code);
    await page.getByRole("button", { name: "Create permission" }).click();
    await expect(page.getByRole("cell", { name: code, exact: true })).toBeVisible();
  }

  await page.getByRole("tab", { name: /Roles/ }).click();
  await page.getByRole("button", { name: "New role" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Viewer");
  await page.getByRole("checkbox", { name: /vehicle\.read/ }).check();
  await page.getByRole("button", { name: "Create role" }).click();
  await expect(page.getByRole("button", { name: "Viewer", exact: true })).toBeVisible();

  // A user, then the role.
  await page.getByRole("link", { name: "Users" }).first().click();
  await page.getByRole("button", { name: "New user" }).click();
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill("a-long-enough-pass-1");
  await page.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByRole("heading", { name: username, level: 1 })).toBeVisible();

  await page.getByRole("button", { name: "Give access to an application" }).click();
  await page.getByLabel("Application", { exact: true }).selectOption(key);
  await page.getByRole("checkbox", { name: /Viewer/ }).check();
  await page.getByRole("button", { name: "Save roles" }).click();

  // The key-cut strip shows exactly the held bit.
  const strip = page.getByRole("list", { name: /Access key/ });
  await expect(strip).toHaveAccessibleName("Access key. Holds vehicle.read");
  await expect(page.getByText("1 of 2 permissions")).toBeVisible();
});

test("a person without the Admin role only sees their own account, and can turn on TOTP", async ({
  page,
  context,
}) => {
  test.setTimeout(90_000); // waits for a fresh 30-second TOTP step
  // Create the person as admin, then sign out.
  const username = unique("bob.");
  const password = "another-long-pass-1";
  await signInAsAdmin(page);
  await page.goto("/users?create=true");
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByRole("heading", { name: username, level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await page.waitForURL(/\/login/);
  await context.clearCookies();

  // As the person: the admin pages are out of reach.
  await signIn(page, username, password);
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);
  await page.goto("/users");
  await expect(page).toHaveURL(/\/account/);

  // Turn on TOTP with the QR code's secret.
  await page.getByRole("tab", { name: "Password and MFA" }).click();
  await page.getByRole("button", { name: "Set up" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Current password").fill(password);
  await dialog.getByRole("button", { name: "Continue" }).click();
  await expect(dialog.getByRole("img", { name: "Authenticator setup QR code" })).toBeVisible();
  const secret = (await dialog.locator("code").textContent())!.trim();
  await dialog.getByLabel("Digit 1").click();
  await page.keyboard.type(totp(secret));
  await expect(page.getByText("Authenticator app turned on")).toBeVisible();

  // Next sign-in asks for a code.
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await page.waitForURL(/\/login/);
  await signIn(page, username, password);
  await expect(page.getByRole("heading", { name: "Enter your code" })).toBeVisible();
  // A fresh time step, so the code isn't the one already used for setup.
  await page.waitForTimeout(31_000 - (Date.now() % 30_000));
  await page.getByLabel("Digit 1").click();
  await page.keyboard.type(totp(secret));
  await expect(page).toHaveURL(/\/account/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(username);
});
