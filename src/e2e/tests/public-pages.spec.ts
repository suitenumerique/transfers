import { expect, test } from "@playwright/test";
import { API_URL } from "../playwright.config";
import { signIn, USER2 } from "../helpers/auth";

// Pages a visitor reaches without signing in.

test("the landing page invites to sign in", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Send and receive in a snap" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("the language choice is remembered", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Language: English" }).click();
  await page.getByRole("menuitem", { name: "Français" }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: /Français/ })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Envoyer et recevoir en un clin d'œil" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Se connecter" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", /fr/);
});

test("unknown links say so", async ({ page }) => {
  await page.goto("/t/does-not-exist");
  await expect(page.getByText("This link does not exist.")).toBeVisible();
});

test("a failed sign-in lands on the error page", async ({ page }) => {
  await page.goto("/errors?reason=access_denied");
  await expect(page.getByText("Access denied")).toBeVisible();
  await page.goto("/errors");
  await expect(page.getByText("Sign-in failed")).toBeVisible();
});

test("signed-in pages send a visitor back to the landing page", async ({ page }) => {
  await page.goto("/transfers/00000000-0000-4000-8000-000000000000");
  await expect(page).toHaveURL(/localhost:7980\/$/);
  await expect(
    page.getByRole("heading", { name: "Send and receive in a snap" }),
  ).toBeVisible();
});

// Its own sign-in: logging out ends the session, which the saved ones of
// the other tests must keep.
test("an agent signs in and out", async ({ page, playwright }) => {
  await signIn(page, USER2);
  // Keeps the session cookie after the browser has dropped its own.
  const oldSession = await playwright.request.newContext({
    storageState: await page.context().storageState(),
  });
  const before = await oldSession.get(`${API_URL}/api/v1.0/users/me/`);
  expect(before.status()).toBe(200);
  await page.getByRole("button", { name: "Open user menu" }).click();
  // The kit renders the action as text, not as a button.
  await page
    .getByRole("dialog", { name: "User menu" })
    .getByText("Logout", { exact: true })
    .click();
  await page.waitForURL(/localhost:7980\/$/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  // The session is gone on the server, not just the cookie in the browser.
  const after = await oldSession.get(`${API_URL}/api/v1.0/users/me/`);
  expect(after.status()).toBe(401);
  await oldSession.dispose();
});
