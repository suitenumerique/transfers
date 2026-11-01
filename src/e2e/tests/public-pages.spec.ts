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
  await page.addInitScript(() =>
    window.localStorage.setItem("transfers_language", "fr-FR"),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Envoyer et recevoir en un clin d'œil" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Se connecter" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", /fr/);
});

test("unknown links say so", async ({ page }) => {
  await page.goto("/t/does-not-exist");
  await expect(page.getByText("This link does not exist.")).toBeVisible();
  await page.goto("/d/does-not-exist");
  await expect(page.getByText("This deposit link does not exist.")).toBeVisible();
});

test("a failed sign-in lands on the error page", async ({ page }) => {
  await page.goto("/errors?reason=access_denied");
  await expect(page.getByText("Access denied")).toBeVisible();
  await page.goto("/errors");
  await expect(page.getByText("Sign-in failed")).toBeVisible();
});

test("signed-in pages send a visitor back to the landing page", async ({ page }) => {
  await page.goto("/spaces");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

// Its own sign-in: logging out ends the session, which the saved ones of
// the other tests must keep.
test("an agent signs in and out", async ({ page }) => {
  await signIn(page, USER2);
  await page.goto(`${API_URL}/api/v1.0/logout/`);
  await page.waitForURL(/localhost:7980/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  // The session is gone, not just the page.
  const response = await page.request.get(`${API_URL}/api/v1.0/users/me/`);
  expect(response.status()).toBe(401);
});
