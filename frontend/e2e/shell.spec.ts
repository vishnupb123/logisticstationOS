import { expect, test } from "./fixtures.ts";

const ROUTES: { path: string; heading: string; badge: RegExp }[] = [
  { path: "/", heading: "Station Overview", badge: /synthetic data/i },
  { path: "/live", heading: "Live Operations", badge: /simulated run/i },
  { path: "/induct", heading: "Induct & Sortation", badge: /synthetic data/i },
  { path: "/stow", heading: "Stow & Jackpot", badge: /synthetic data/i },
  { path: "/investigations", heading: "AI Investigations", badge: /synthetic data/i },
  { path: "/simulation", heading: "Digital Twin Scenario Runner", badge: /simulated run/i },
  { path: "/rl", heading: "RL Policy Comparison", badge: /simulated run/i },
  { path: "/decisions", heading: "Decisions & Audit History", badge: /simulated run/i },
];

test("backend health is shown as operational in the top bar", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("health-indicator")).toContainText("All systems operational");
});

for (const route of ROUTES) {
  test(`${route.path} renders with a data-source badge (never "live")`, async ({ page }) => {
    await page.goto(route.path);
    await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
    await expect(page.locator(".data-source-badge").first()).toHaveText(route.badge);
    await expect(page.locator(".query-state--error")).toHaveCount(0);
  });
}

test("health stays operational while the overview loads all analytics at once", async ({ page }) => {
  // Regression for the DuckDB read-write probe vs. read-only query clash.
  await page.goto("/");
  await expect(page.getByTestId("kpi-inducted")).toBeVisible();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.reload();
  await expect(page.getByTestId("kpi-inducted")).toBeVisible();
  await expect(page.getByTestId("health-indicator")).toContainText("All systems operational");
});
