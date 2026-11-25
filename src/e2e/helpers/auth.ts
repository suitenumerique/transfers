import { expect, type Browser, type Page } from "@playwright/test";
import { OUTPUT_DIR } from "../playwright.config";

// The dev users of src/keycloak/realm.json: the password is the name
// before the @.
export interface DevUser {
  email: string;
  password: string;
}

const devUser = (name: string): DevUser => ({
  email: `${name}@example.local`,
  password: name,
});

export const USER1 = devUser("user1");
export const USER2 = devUser("user2");
export const USER3 = devUser("user3");
export const USERS = [USER1, USER2, USER3];

export function storageStateOf(user: DevUser): string {
  return `${OUTPUT_DIR}/.auth/${user.email}.json`;
}

// Fill the Keycloak login form the app redirected to, and wait to be back
// in the app.
export async function fillKeycloak(page: Page, user: DevUser) {
  await page.waitForURL(/localhost:7902\/realms\/transfers\//);
  await page.locator("#username").fill(user.email);
  await page.locator("#password").fill(user.password);
  await page.locator("#kc-login").click();
  await page.waitForURL(/localhost:7980/);
}

// Sign in from the landing page, the way a visitor does.
export async function signIn(page: Page, user: DevUser) {
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).first().click();
  await fillKeycloak(page, user);
  await expect(page.getByRole("link", { name: "New transfer" })).toBeVisible();
}

// A page with no session. ``browser.newPage()`` would not do: in a test file
// with ``test.use({ storageState })`` it inherits that signed-in session.
export async function anonymousPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  });
  return context.newPage();
}

// A page signed in as ``user``, beside the test's own page.
export async function pageAs(browser: Browser, user: DevUser): Promise<Page> {
  const context = await browser.newContext({
    storageState: storageStateOf(user),
  });
  return context.newPage();
}
