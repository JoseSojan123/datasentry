import { expect, test } from "@playwright/test";

/**
 * The core story in the browser: a demo visitor opens the highest-priority incident,
 * approves the quarantine remediation, runs it, and sees the incident resolved only
 * after verification, with the investigation graph switching to "contained".
 */
test("demo incident: quarantine, verify and resolve", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  // Seeding the demo workspace runs real profiling, checks and drift, so allow it time.
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 60_000 });

  await page.getByRole("link", { name: /card_transactions: allowed values/ }).first().click();
  await expect(page.getByRole("heading", { name: "Investigation" })).toBeVisible();
  await expect(page.getByText("propagating", { exact: true })).toBeVisible();
  await expect(page.getByText("Blast radius")).toBeVisible();

  // The missing-value policy is listed but refused by its precondition (32% > 20% limit).
  await expect(page.getByText("share of rows changed within limit")).toBeVisible();

  const card = page.locator("article", { hasText: "Quarantine failing version" });
  await card.getByRole("button", { name: /Quarantine failing version/ }).click();
  await card.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: /Approve/ }).click();
  await card.getByRole("button", { name: "Run and verify" }).click();

  await expect(page.getByText("Resolved after verification").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("contained", { exact: true })).toBeVisible();
  await expect(page.getByText(/quarantined batch still contains the defects/).first()).toBeVisible();
});

test("public pages have no horizontal overflow and need sign-in for the console", async ({ page }) => {
  await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.goto("/incidents");
  await expect(page).toHaveURL(/\/login\?next=%2Fincidents/);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
});
