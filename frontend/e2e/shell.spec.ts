import { expect, test } from "./fixtures.ts";

const ROUTES: { path: string; heading: string; badge: RegExp }[] = [
  { path: "/", heading: "Station Overview", badge: /synthetic data/i },
  { path: "/command", heading: "Station Command Center", badge: /simulated run/i },
  { path: "/work-items", heading: "Work Items", badge: /simulated run/i },
  { path: "/inbound", heading: "Receive", badge: /simulated run/i },
  { path: "/truckfile", heading: "Truckfile & Ferries", badge: /synthetic data/i },
  { path: "/induct", heading: "Sort Overview", badge: /simulated run/i },
  { path: "/stow", heading: "Stow & Buffers", badge: /simulated run/i },
  { path: "/problem-solve", heading: "Problem Solve", badge: /simulated run/i },
  { path: "/packages", heading: "Package Summary", badge: /simulated run/i },
  { path: "/outbound", heading: "Outbound Overview", badge: /simulated run/i },
  { path: "/pick", heading: "Pick", badge: /simulated run/i },
  { path: "/stage", heading: "Stage", badge: /simulated run/i },
  { path: "/dispatch", heading: "Dispatch & DSP Coordination", badge: /simulated run/i },
  { path: "/high-value", heading: "High-Value Processing", badge: /simulated run/i },
  { path: "/associates", heading: "Associates", badge: /simulated run/i },
  { path: "/labor", heading: "Shift Plan", badge: /simulated run/i },
  { path: "/station", heading: "Station & Resources", badge: /simulated run/i },
  { path: "/agent", heading: "Agent Console", badge: /simulated run/i },
  { path: "/agent/investigations", heading: "Station Agent", badge: /simulated run/i },
  { path: "/assistant", heading: "Station Assistant", badge: /simulated run/i },
  { path: "/live", heading: "Live Operations", badge: /simulated run/i },
  { path: "/investigations", heading: "Flow Investigations", badge: /synthetic data/i },
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
