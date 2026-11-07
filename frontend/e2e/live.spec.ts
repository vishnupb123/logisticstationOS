import { expect, test } from "./fixtures.ts";

test("live run visibly progresses frame by frame", async ({ page }) => {
  await page.goto("/live");
  await page.getByLabel("Scenario").selectOption("normal_operations.yaml");
  await page.getByLabel("Playback").selectOption({ label: "Standard" });
  await page.getByRole("button", { name: "Start live run" }).click();

  await expect(page.getByTestId("live-status")).toContainText("Streaming");
  const clock = page.getByTestId("sim-clock");
  await expect(clock).toBeVisible();
  const first = await clock.innerText();
  // The simulated clock must advance while we watch — the whole point.
  await expect(clock).not.toHaveText(first, { timeout: 10_000 });

  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByTestId("live-status")).toContainText("Stopped");
});

test("an unpaced live run completes with every planned parcel accounted for", async ({ page }) => {
  await page.goto("/live");
  await page.getByLabel("Scenario").selectOption("rl_stow_balancing.yaml");
  await page.getByLabel("Playback").selectOption({ label: "Instant (no pacing)" });
  await page.getByRole("button", { name: "Start live run" }).click();

  await expect(page.getByTestId("live-status")).toContainText("Run complete", { timeout: 60_000 });
  await expect(page.getByText(/(\d+)\/\1 parcels processed \(100%\)/)).toBeVisible();
  const stowed = await page.getByTestId("kpi-stowed").locator(".kpi__value").innerText();
  expect(Number(stowed)).toBeGreaterThan(0);
  await expect(page.getByTestId("funnel-stowed")).toContainText(stowed);
  await expect(page.getByTestId("event-ticker").locator(".ticker__row").first()).toBeVisible();
  await expect(page.getByTestId("kpi-dock-to-stow")).not.toContainText("—");
});
