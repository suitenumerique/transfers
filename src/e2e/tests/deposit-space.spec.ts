import { expect, test, type Page } from "@playwright/test";
import { anonymousPage, storageStateOf, USER1 } from "../helpers/auth";
import { deposit, depositCode, newDepositor } from "../helpers/deposits";
import { downloadedBytes, makeFile, uniqueTitle } from "../helpers/files";
import { linkIn, waitForMail } from "../helpers/mail";

test.use({ storageState: storageStateOf(USER1) });

// Create a space from /spaces and open its page. Returns its public link.
async function createSpace(page: Page, name: string): Promise<string> {
  await page.goto("/spaces");
  await expect(page.getByRole("heading", { name: "Deposit spaces" })).toBeVisible();
  await page.getByLabel("New space name").fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  // The page's list, not the sidebar, which names the space too.
  await page
    .locator(".deposits__list")
    .getByRole("link", { name: new RegExp(name) })
    .click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  const link = await page.getByLabel("Deposit link").inputValue();
  expect(link).toMatch(/^http:\/\/localhost:7980\/d\/[\w-]+$/);
  return link;
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
    return ((await response.json()) as { public_token: string }).public_token;
  }, page.url());
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

test("a closed space stops taking deposits", async ({ page, browser }) => {
  const name = uniqueTitle("Closing space");
  const link = await createSpace(page, name);

  await page.getByRole("button", { name: "Close the space" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close the space" })
    .click();
  await expect(
    page.getByText("This space is closed: its link no longer accepts deposits."),
  ).toBeVisible();

  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await expect(
    visitor.getByText("This deposit link was closed by its owner."),
  ).toBeVisible();
  await visitor.context().close();
});
