import { expect, test } from "./fixtures.ts";

test("agent fallback findings survive a reload (persisted, not cache-only)", async ({ page }) => {
  await page.goto("/investigations");
  await page.getByRole("button", { name: "Run Flow Intelligence Agent" }).click();
  await expect(page.getByRole("button", { name: "Run Flow Intelligence Agent" })).toBeEnabled({
    timeout: 60_000,
  });
  await page.locator(".list-item__link").first().click();
  await expect(page.getByRole("heading", { name: "Findings" })).toBeVisible();
  // A full reload bypasses the React Query cache: only the persisted row counts.
  await page.reload();
  await expect(page.locator(".evidence-badge").first()).toBeVisible();
  await expect(page.getByText("No findings.")).toHaveCount(0);
});

test.describe("RBAC", () => {
  // The refused approval is a real 403 from the API, which the browser
  // logs as a failed resource load — expected here, and only here.
  test.use({ allowedConsoleErrors: [/status of 403/] });

  test("an operator cannot approve, a supervisor can", async ({ page }) => {
  await page.goto("/decisions");
  await page.getByLabel("Context / trigger").fill(`e2e RBAC check ${Date.now()}`);
  await page.getByRole("button", { name: "Propose decision" }).click();
  await expect(page).toHaveURL(/\/decisions\/[0-9a-f-]+$/, { timeout: 60_000 });
  await expect(page.locator(".status-pill").first()).toHaveText(/pending_approval/i);

  await page.getByPlaceholder("your name").fill("e2e-operator");
  await page.locator(".role-picker select").selectOption("operator");
  await page.getByLabel("Selected candidate (for approval)").selectOption("status_quo");
  await page.getByLabel("Rationale").fill("e2e: operator should be refused");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.locator(".query-state--error")).toContainText("403");

  await page.locator(".role-picker select").selectOption("supervisor");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.locator(".status-pill").first()).toHaveText(/approved/i);
});
});
