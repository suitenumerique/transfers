import { test as setup } from "@playwright/test";
import { signIn, storageStateOf, USERS } from "../helpers/auth";

// One real OIDC sign-in per dev user, through the local Keycloak. The tests
// start from these saved sessions instead of signing in again.
for (const user of USERS) {
  setup(`sign in as ${user.email}`, async ({ page }) => {
    await signIn(page, user);
    await page.context().storageState({ path: storageStateOf(user) });
  });
}
