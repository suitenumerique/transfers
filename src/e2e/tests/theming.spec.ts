import { expect, test, type Page } from "@playwright/test";
import { FRONTEND_URL, OPERATOR_URL } from "../playwright.config";
import { signIn, USER3 } from "../helpers/auth";
import { makeFile, uniqueTitle } from "../helpers/files";
import { linkIn, waitForMail } from "../helpers/mail";
import { createTransfer } from "../helpers/transfers";

// Runtime configuration: one image, N operators.
//
// The stack serves the same container on two names (env.d/e2e/backend.e2e):
// localhost:7980 is the neutral deployment, opsn1.localhost:7980 an operator
// with its own brand. Most of this is anonymous — the theme reaches a visitor
// before any session exists, which is where it matters most, since the
// landing page is the first thing a citizen sees.
//
// What a unit test cannot say and this can: the browser's Host survives the
// whole chain (dev server proxy, then Django), the colours land on the
// components that actually read the tokens, and a section this build does not
// know never reaches the page.

// The compiled palette's brand rung (src/frontend/src/styles/
// cunningham-tokens.css). The neutral deployment must still show it: a theme
// leaking across domains would show the operator's red here. Lower case
// because that is what a custom property comes back as once the stylesheet
// has been minified, and a hex colour's case means nothing: `token` below
// folds both sides.
const COMPILED_BRAND_550 = "#5e5cd0";
const COMPILED_BRAND_550_RGB = "rgb(94, 92, 208)";

// What env.d/e2e/backend.e2e gives opsn1.localhost.
const OPERATOR_BRAND_550 = "#b5363f";
const OPERATOR_BRAND_550_RGB = "rgb(181, 54, 63)";

/** A Cunningham token, as the browser resolved it, case folded. */
const token = (page: Page, name: string): Promise<string> =>
  page.evaluate(
    (property) =>
      getComputedStyle(document.documentElement)
        .getPropertyValue(property)
        .trim()
        .toLowerCase(),
    name,
  );

/** The ``<link rel="icon">`` slots, paired with the scheme each answers for. */
const favicons = (page: Page): Promise<[string, string | null][]> =>
  page.evaluate(() =>
    [...document.querySelectorAll<HTMLLinkElement>('link[rel="icon"]')].map(
      (link) => [link.media, link.getAttribute("href")] as [string, string | null],
    ),
  );

// The sign-in affordance appears in the header too, so assertions about the
// landing page say which one they mean.
const landing = (page: Page) => page.locator("section.home-landing");

// ProConnect's button carries no accessible name today: ui-kit draws the
// brand as a CSS background image and labels nothing, so there is no role +
// name to select it by. Worth raising upstream — a screen reader announces
// "button" on the only way into the service. Until then, its class.
const proConnectButton = (page: Page) =>
  page.locator("button.pro-connect-button");

test("the neutral deployment keeps the product's own identity", async ({
  page,
}) => {
  await page.goto(FRONTEND_URL);

  // Waiting on a link from the theme is waiting on /config/: once it is
  // there, this domain's configuration has been applied, so what follows
  // reads a settled page rather than a racing one.
  await expect(
    landing(page).getByRole("link", { name: "Learn more" }),
  ).toHaveAttribute("href", "https://learn.e2e.test/base");

  // This domain's configuration carries links, no branding, so the compiled
  // palette shows through untouched — on the token and on the button.
  expect(await token(page, "--c--globals--colors--brand-550")).toBe(
    COMPILED_BRAND_550,
  );
  const signIn = landing(page).getByRole("button", { name: "Sign in" });
  await expect(signIn).toBeVisible();
  await expect(signIn).toHaveCSS("background-color", COMPILED_BRAND_550_RGB);

  // Neither the operator's mark nor its identity provider.
  await expect(
    page.getByRole("img", { name: "OPSN1", exact: true }),
  ).toHaveCount(0);
  await expect(proConnectButton(page)).toHaveCount(0);
});

test("an operator's domain is themed at runtime, with no rebuild", async ({
  page,
}) => {
  await page.goto(OPERATOR_URL);

  // The token the operator overrode, then the button that reads it. The first
  // failing alone means the resolver or the applier; the second alone means
  // we overrode a rung Cunningham's components do not use, which is the
  // mistake the README warns about.
  await expect
    .poll(() => token(page, "--c--globals--colors--brand-550"))
    .toBe(OPERATOR_BRAND_550);
  const signIn = landing(page).locator("button.pro-connect-button");
  await expect(signIn).toHaveCSS("background-color", OPERATOR_BRAND_550_RGB);
  // Same component, same classes as the neutral domain's button: nothing was
  // recompiled, the custom properties it reads were replaced underneath it.
  await expect(signIn).toHaveClass(/c__button--brand--primary/);

  // ``fontFamily`` declares a family, it serves no file: Georgia is there for
  // the assertion precisely because every machine already has it.
  await expect
    .poll(() =>
      page.evaluate(() => getComputedStyle(document.body).fontFamily),
    )
    .toContain("Georgia");

  // The operator's marks, in the header and on the landing page. Exact: the
  // banner below is named "OPSN1 file transfer", which a substring match
  // would pick up too.
  await expect(
    page.getByRole("img", { name: "OPSN1", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "OPSN1 file transfer" }),
  ).toBeVisible();

  // ProConnect is opt-in per domain: the branded button carries the French
  // State's mark, so it must not show on an instance federated elsewhere.
  await expect(proConnectButton(page)).toHaveCount(2); // header + landing
  await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0);

  await expect(
    landing(page).getByRole("link", { name: "Learn more" }),
  ).toHaveAttribute("href", "https://learn.e2e.test/opsn1");
});

test("both favicon slots follow the theme, one per colour scheme", async ({
  page,
}) => {
  await page.goto(FRONTEND_URL);
  // Untouched by this domain's configuration: both slots keep the product's
  // icon, and both are declared, which is what gives the dark one somewhere
  // to apply.
  await expect.poll(() => favicons(page)).toEqual([
    ["(prefers-color-scheme: light)", "/images/transfers-favicon.svg"],
    ["(prefers-color-scheme: dark)", "/images/transfers-favicon.svg"],
  ]);

  await page.goto(OPERATOR_URL);
  await expect.poll(() => favicons(page)).toEqual([
    ["(prefers-color-scheme: light)", "/images/transfers-favicon.svg"],
    ["(prefers-color-scheme: dark)", "/images/transfers-icon.svg"],
  ]);
});

test("the support link is the one its own operator answers", async ({
  page,
}) => {
  // Not the landing page: the theme has to reach every page, and the error
  // page is where a stuck user looks for help.
  await page.goto(`${FRONTEND_URL}/errors`);
  await expect(
    page.getByRole("link", { name: "Contact support" }),
  ).toHaveAttribute("href", "https://support.e2e.test/base");

  await page.goto(`${OPERATOR_URL}/errors`);
  await expect(
    page.getByRole("link", { name: "Contact support" }),
  ).toHaveAttribute("href", "https://support.e2e.test/opsn1");
});

test("/config/ resolves on the host the browser used", async ({ request }) => {
  const base = await (
    await request.get(`${FRONTEND_URL}/api/v1.0/config/`)
  ).json();
  const operator = await (
    await request.get(`${OPERATOR_URL}/api/v1.0/config/`)
  ).json();

  // Same build, same compiled palette: what differs is resolved per request.
  expect(operator.FRONTEND_THEME).toBe(base.FRONTEND_THEME);

  expect(base.theme_customization.help.support_url).toBe(
    "https://support.e2e.test/base",
  );
  // Nothing to apply on this domain — which is what makes the neutral
  // assertions above a statement about the configuration, not about timing.
  expect(base.theme_customization.colors).toBeUndefined();

  expect(operator.theme_customization.help.support_url).toBe(
    "https://support.e2e.test/opsn1",
  );
  expect(
    operator.theme_customization.colors[
      "--c--globals--colors--brand-550"
    ].toLowerCase(),
  ).toBe(OPERATOR_BRAND_550);
  // An override states only what differs: the base's help link is still
  // there, beside the support link that replaced it. Adding a domain never
  // means restating a whole theme.
  expect(operator.theme_customization.help.documentation_url).toBe(
    "https://help.e2e.test/docs",
  );
});

test("a key this build does not know travels, a section does not", async ({
  request,
}) => {
  const response = await request.get(`${FRONTEND_URL}/api/v1.0/config/`);
  const config = await response.json();

  // The theme is deliberately not validated key by key: that is what lets the
  // Suite's products share one file without each knowing every key in it.
  expect(config.theme_customization.e2e_unknown_key).toEqual({ kept: true });

  // A *section* is the opposite: unknown means private, so a shared file
  // carrying another product's secrets cannot leak through /config/.
  expect(config.e2e_private).toBeUndefined();
  expect(JSON.stringify(config)).not.toContain("sentinel");
});

// Everything above is read-only and anonymous. This one signs in on the
// operator's domain, so it runs in its own context.
test.describe("an operator's own links", () => {
  test.use({ baseURL: OPERATOR_URL });

  test("an invitation links back to the domain it was sent from", async ({
    page,
  }, testInfo) => {
    // The link in the email is built from the request's origin, carried from
    // the view into the task: a background job has no request, and an
    // instance-wide setting names one host for every domain. Get it wrong and
    // the recipient lands on another operator's site -- with a session cookie
    // set for a host they are not on, so apparently signed out.
    await signIn(page, USER3);

    const title = uniqueTitle("Operator invitation");
    const recipient = "user2@example.local";
    await createTransfer(page, {
      files: [await makeFile(testInfo, "operator.txt", 1_000)],
      title,
      mode: "email",
      recipients: [recipient],
    });

    const invitation = await waitForMail({ to: recipient, body: title });
    expect(new URL(linkIn(invitation, "/t/")).origin).toBe(OPERATOR_URL);
  });
});
