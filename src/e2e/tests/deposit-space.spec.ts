import { expect, test, type Page } from "@playwright/test";
import {
  anonymousPage,
  fillKeycloak,
  pageAs,
  storageStateOf,
  USER1,
  USER2,
} from "../helpers/auth";
import { deposit, depositCode, newDepositor } from "../helpers/deposits";
import { downloadedBytes, makeFile, uniqueTitle } from "../helpers/files";
import { createUser } from "../helpers/keycloak";
import { linkIn, waitForMail } from "../helpers/mail";

test.use({ storageState: storageStateOf(USER1) });

interface SpaceOptions {
  singleUse?: boolean;
  noEmailCheck?: boolean;
  endToEnd?: boolean;
}

// Create a space from /spaces, which opens its page. Returns its public
// link.
async function createSpace(
  page: Page,
  name: string,
  options: SpaceOptions = {},
): Promise<string> {
  await page.goto("/spaces");
  await expect(page.getByRole("heading", { name: "Deposit spaces" })).toBeVisible();
  await page.getByLabel("New space name").fill(name);
  if (options.singleUse) {
    await page.getByLabel("Close the link after the first deposit").check();
  }
  if (options.noEmailCheck) {
    // Checked, the box's checkmark takes the clicks: click its label.
    await page.getByText("Check the depositor's email with a code").click();
    await expect(
      page.getByLabel("Check the depositor's email with a code"),
    ).not.toBeChecked();
  }
  if (options.endToEnd) {
    await page.getByLabel("End-to-end encryption").check();
  }
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  const link = await page.getByLabel("Deposit link").inputValue();
  // An end-to-end link carries its key in the fragment.
  expect(link).toMatch(
    options.endToEnd
      ? /^http:\/\/localhost:7980\/d\/[\w-]+#[\w-]{43}$/
      : /^http:\/\/localhost:7980\/d\/[\w-]+$/,
  );
  return link;
}

// The agent's page of the deposit the notification for ``depositorEmail``
// points to. ``title``, unique to the test, tells apart the notifications of
// a depositor shared by several tests (a dev user).
async function openDeposit(
  page: Page,
  to: string,
  depositorEmail: string,
  title?: string,
) {
  const notification = await waitForMail({
    to,
    subject: new RegExp(`Nouveau dépôt de ${depositorEmail}`),
    ...(title ? { body: title } : {}),
  });
  await page.goto(linkIn(notification, "/transfers/"));
}

test("someone without an account deposits files on a space", async ({
  page,
  browser,
}, testInfo) => {
  const spaceName = uniqueTitle("Space");
  const link = await createSpace(page, spaceName);

  const files = [
    await makeFile(testInfo, "invoice.pdf", 60_000),
    await makeFile(testInfo, "id-card.png", 8_000),
  ];
  const depositor = newDepositor();
  const title = uniqueTitle("Deposit");

  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await expect(
    visitor.getByRole("heading", { name: `Send files to ${spaceName} (User Un)` }),
  ).toBeVisible();
  await deposit(visitor, depositor, title, files);
  await visitor.context().close();

  // The depositor gets a receipt, the agent a notification.
  await waitForMail({
    to: depositor.email,
    subject: /Votre dépôt a bien été transmis/,
    body: title,
  });
  const notification = await waitForMail({
    to: "user1@example.local",
    subject: new RegExp(`Nouveau dépôt de ${depositor.email}`),
  });
  const detailUrl = linkIn(notification, "/transfers/");

  // The deposit is listed on the space, and opens on its detail page.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Deposits received" })).toBeVisible();
  await page
    .locator(".deposits__list")
    .getByRole("link", { name: new RegExp(title) })
    .click();
  await expect(page).toHaveURL(detailUrl);
  await expect(
    page.getByText(
      `Deposited by ${depositor.name} (${depositor.email}, verified address).`,
    ),
  ).toBeVisible();
  await expect(page.getByText("Files deposited").first()).toBeVisible();

  // Files the antivirus did not check ask for a confirmation first.
  const file = files[0];
  await page.getByRole("button", { name: `Download ${file.name}` }).click();
  const warning = page.getByRole("dialog");
  await expect(warning.getByText("Files not checked by the antivirus")).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    warning.getByRole("button", { name: "Download anyway" }).click(),
  ]);
  expect((await downloadedBytes(download)).equals(file.content)).toBe(true);
});

test("a deposit link is the owner's alone to open", async ({
  page,
  browser,
}, testInfo) => {
  const link = await createSpace(page, uniqueTitle("Private space"));
  const depositor = newDepositor();
  const title = uniqueTitle("Private deposit");
  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await deposit(visitor, depositor, title, [await makeFile(testInfo, "x.txt", 100)]);

  const notification = await waitForMail({
    to: "user1@example.local",
    subject: new RegExp(`Nouveau dépôt de ${depositor.email}`),
  });
  // The public token of a deposit is no capability: an outsider gets 404.
  await page.goto(linkIn(notification, "/transfers/"));
  const token = await page.evaluate(async (url) => {
    const id = url.split("/transfers/")[1];
    const response = await fetch(`http://localhost:7981/api/v1.0/transfers/${id}/`, {
      credentials: "include",
    });
    if (!response.ok) return "";
    return ((await response.json()) as { public_token?: string }).public_token ?? "";
  }, page.url());
  expect(token).not.toBe("");
  // The API answers an outsider as for an unknown link, and the page says so.
  const info = await visitor.request.get(
    `http://localhost:7981/api/v1.0/downloads/${token}/`,
  );
  expect(info.status()).toBe(404);
  await visitor.goto(`/t/${token}`);
  await expect(visitor.getByText("This link does not exist.")).toBeVisible();
  await visitor.context().close();
});

test("a wrong code says how many tries are left", async ({ page, browser }) => {
  const link = await createSpace(page, uniqueTitle("Code space"));
  const depositor = newDepositor();
  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await visitor.getByLabel("Your name").fill(depositor.name);
  await visitor.getByLabel("Your email address").fill(depositor.email);
  await visitor.getByRole("button", { name: "Receive a code" }).click();

  const code = await depositCode(depositor.email);
  const wrong = String((Number(code) + 1) % 1_000_000).padStart(6, "0");
  await visitor.getByLabel("Code").fill(wrong);
  await visitor.getByRole("button", { name: "Check the code" }).click();
  await expect(
    visitor.getByText("This code is not right. 4 attempts left."),
  ).toBeVisible();
  await visitor.context().close();
});

test("a single-use space closes after its first deposit", async ({
  page,
  browser,
}, testInfo) => {
  const link = await createSpace(page, uniqueTitle("Single-use space"), {
    singleUse: true,
  });
  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await deposit(visitor, newDepositor(), uniqueTitle("Only deposit"), [
    await makeFile(testInfo, "x.txt", 100),
  ]);

  await page.reload();
  await expect(
    page.getByText(/This space is closed: it took its one deposit on/),
  ).toBeVisible();
  await visitor.goto(link);
  await expect(
    visitor.getByText("This recipient no longer accepts deposits."),
  ).toBeVisible();
  await visitor.context().close();
});

test("deleting a space deletes its deposits", async ({ page, browser }, testInfo) => {
  const link = await createSpace(page, uniqueTitle("Doomed space"));
  const spaceUrl = page.url();
  const depositor = newDepositor();
  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await deposit(visitor, depositor, uniqueTitle("Doomed deposit"), [
    await makeFile(testInfo, "x.txt", 100),
  ]);
  await openDeposit(page, USER1.email, depositor.email);
  const depositUrl = page.url();

  await page.goto(spaceUrl);
  await page.getByRole("button", { name: "Delete the space" }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByText("the space's deposit is deleted with its files"),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Delete the space" }).click();
  await expect(page).toHaveURL(/\/spaces$/);

  await visitor.goto(link);
  await expect(visitor.getByText("This deposit link does not exist.")).toBeVisible();
  await visitor.context().close();
  await page.goto(depositUrl);
  await expect(page.getByText("Transfer not found.")).toBeVisible();
  await expect(page.getByRole("heading", { name: /Doomed deposit/ })).toHaveCount(0);
});

test("a deposit is deleted at once, without deactivating it", async ({
  page,
  browser,
}, testInfo) => {
  const link = await createSpace(page, uniqueTitle("Space"));
  const depositor = newDepositor();
  const title = uniqueTitle("Deposit to delete");
  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await deposit(visitor, depositor, title, [await makeFile(testInfo, "x.txt", 100)]);
  await visitor.context().close();

  await openDeposit(page, USER1.email, depositor.email);
  const depositUrl = page.url();
  await expect(page.getByRole("button", { name: "Deactivate" })).toHaveCount(0);
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete permanently" })
    .click();
  await expect(page).toHaveURL("/");
  await page.goto(depositUrl);
  await expect(page.getByText("Transfer not found.")).toBeVisible();
  await expect(page.getByRole("heading", { name: title })).toHaveCount(0);
});

test("a space can take deposits without checking the email", async ({
  page,
  browser,
}, testInfo) => {
  const link = await createSpace(page, uniqueTitle("Open space"), {
    noEmailCheck: true,
  });
  const depositor = newDepositor();
  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await deposit(
    visitor,
    depositor,
    uniqueTitle("Unchecked deposit"),
    [await makeFile(testInfo, "x.txt", 100)],
    "unverified",
  );
  await visitor.context().close();

  await openDeposit(page, USER1.email, depositor.email);
  await expect(
    page.getByText(
      `Deposited by ${depositor.name} (${depositor.email}, address not verified).`,
    ),
  ).toBeVisible();
});

test("someone signed in with ProConnect deposits without a code", async ({
  page,
  browser,
}, testInfo) => {
  const link = await createSpace(page, uniqueTitle("Space"));
  const colleague = await pageAs(browser, USER2);
  await colleague.goto(link);
  const signedInEmail = colleague.getByLabel("Your email address");
  await expect(signedInEmail).toHaveValue("user2@example.local");
  await expect(signedInEmail).toBeDisabled();
  const title = uniqueTitle("Signed-in deposit");
  await deposit(
    colleague,
    { name: "", email: USER2.email },
    title,
    [await makeFile(testInfo, "x.txt", 100)],
    "signed-in",
  );
  await colleague.context().close();

  await openDeposit(page, USER1.email, USER2.email, title);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(
    page.getByText(/Deposited by .* \(user2@example\.local, verified address\)\./),
  ).toBeVisible();
});

test("an end-to-end space keeps its key in the link", async ({
  page,
  browser,
}, testInfo) => {
  const link = await createSpace(page, uniqueTitle("Sealed space"), {
    endToEnd: true,
  });

  // Without its key the link cannot deposit.
  const visitor = await anonymousPage(browser);
  await visitor.goto(link.split("#")[0]);
  await expect(visitor.getByText(/This link is incomplete/)).toBeVisible();

  const file = await makeFile(testInfo, "sealed.pdf", 20_000);
  const depositor = newDepositor();
  await visitor.goto("about:blank");
  await visitor.goto(link);
  await deposit(visitor, depositor, uniqueTitle("Sealed deposit"), [file]);
  await visitor.context().close();

  // The browser that made the space kept the key: the files open here.
  await openDeposit(page, USER1.email, depositor.email);
  await expect(page.getByText("Confidential").first()).toBeVisible();
  await page.getByRole("button", { name: `Download ${file.name}` }).click();
  const warning = page.getByRole("dialog");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    warning.getByRole("button", { name: "Download anyway" }).click(),
  ]);
  expect((await downloadedBytes(download)).equals(file.content)).toBe(true);
});

test("a space is shared with a colleague who has never signed in", async ({
  page,
  browser,
}, testInfo) => {
  const name = uniqueTitle("Shared space");
  const link = await createSpace(page, name);
  const member = await createUser("member");
  await page.getByLabel("Email address of the person to add").fill(member.email);
  await page.getByRole("button", { name: "Share", exact: true }).click();
  await expect(page.getByText(member.email)).toBeVisible();

  // The invitation leads there through the sign-in.
  const invitation = await waitForMail({
    to: member.email,
    subject: /a partagé l'espace de dépôt/,
  });
  const colleague = await anonymousPage(browser);
  await colleague.goto(linkIn(invitation, "/spaces/"));
  await colleague.getByRole("button", { name: "Sign in" }).first().click();
  await fillKeycloak(colleague, member);
  await expect(colleague.getByRole("heading", { name })).toBeVisible();
  await expect(colleague.getByText(`Shared with you by ${USER1.email}.`)).toBeVisible();
  await expect(colleague.getByRole("button", { name: "Delete the space" })).toHaveCount(0);

  // They are told of deposits, and open them.
  const depositor = newDepositor();
  const title = uniqueTitle("Shared deposit");
  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await deposit(visitor, depositor, title, [await makeFile(testInfo, "x.txt", 100)]);
  await visitor.context().close();
  await openDeposit(colleague, member.email, depositor.email);
  await expect(colleague.getByRole("heading", { name: title })).toBeVisible();
  await colleague.context().close();
});
