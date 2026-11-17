// v2 operating pages end to end against the running stack: Receive
// linehauls (group-by split + trip drawer), Dwell drill-down, Stow fingers,
// Plan vs. Actual interval toggle, Shift Plan (work groups + opportunities),
// Shift Rotation, and Associates by path.
import type { APIRequestContext } from "@playwright/test";
import { expect, test } from "./fixtures.ts";

const API = process.env.E2E_API_URL ?? "http://localhost:8010";
const SID = `${API}/runtime/sessions/default`;

async function pitchDay(request: APIRequestContext, minute: number, opts: { paused?: boolean } = {}) {
  const r = await request.post(`${API}/runtime/sessions`, { data: { preset: "pitch_day", seed: 3, mode: "advise", speed: 5 } });
  expect(r.ok()).toBeTruthy();
  const s = await request.post(`${SID}/seek`, { data: { minute } });
  expect(s.ok()).toBeTruthy();
  if (opts.paused) await request.post(`${SID}/control`, { data: { paused: true } });
}

test.afterEach(async ({ request }) => {
  await request.post(`${SID}/control`, { data: { paused: false } });
});

test("receive linehauls: group-by cluster splits volume, trip drawer shows legs", async ({ page, request }) => {
  await pitchDay(request, 420);
  await page.goto("/inbound");
  await expect(page.getByRole("heading", { level: 1, name: "Receive" })).toBeVisible();
  await expect(page.getByTestId("receive-ladder")).toContainText("Unplanned");
  await page.getByRole("tab", { name: "Linehauls" }).click();
  const arrived = page.getByTestId("linehaul-arrived");
  await expect(arrived.locator("th", { hasText: /^Volume/ })).toHaveCount(1);
  await page.getByRole("radio", { name: "Cluster" }).check();
  await expect(arrived.locator("th", { hasText: "Volume · A" })).toBeVisible();
  await expect(arrived.locator("th", { hasText: "Volume · B" })).toBeVisible();
  // the split columns of the first trip sum to its manifest volume
  const state = await (await request.get(`${SID}/state`)).json();
  const first = state.views.receive_v2.linehauls.find((t: { status: string }) => t.status === "Arrived");
  const split = Object.values(first.group.cluster as Record<string, number>).reduce((a, b) => a + b, 0);
  expect(split).toBe(first.volume);
  // a ferry trip's drawer shows the legs timeline with the ferry leg
  const ferry = state.views.receive_v2.linehauls.find((t: { via_ferry: boolean }) => t.via_ferry);
  await page.getByTestId(`trip-${ferry.trip_id}`).click();
  const drawer = page.getByTestId("trip-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer.getByTestId("trip-legs").locator("li")).toHaveCount(ferry.legs.length);
  await expect(drawer.getByTestId("trip-legs")).toContainText("Ferry");
  await expect(drawer).toContainText(/pending induct/);
  await drawer.getByTestId("watch-trip").click();
  await expect(drawer.getByRole("status")).toContainText(/watch list/);
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
});

test("dwell: a drill-down count opens a package list of the same length", async ({ page, request }) => {
  await pitchDay(request, 420, { paused: true });
  await page.goto("/packages");
  const tree = page.getByTestId("dwell-cycle");
  await expect(tree).toBeVisible();
  // expand Pending Induct and open one of its sub-status counts
  await tree.getByRole("button", { name: "Pending Induct", exact: true }).click();
  const link = tree.locator(".status-tree__row .count-link").first();
  const n = Number(((await link.textContent()) ?? "").replace(/,/g, ""));
  expect(n).toBeGreaterThan(0);
  await link.click();
  await expect(page.getByTestId("package-list-count")).toHaveText(`${n.toLocaleString("en-US")} package${n === 1 ? "" : "s"}`);
  await page.getByTestId("package-list").getByRole("button", { name: "Close" }).click();
  await expect(page.getByTestId("package-list")).toHaveCount(0);
  // a group-level count too, in the delivery-window view
  await page.getByRole("button", { name: "By scheduled delivery window" }).click();
  const w = page.getByTestId("dwell-window").locator(".status-tree__group .count-link").first();
  const m = Number(((await w.textContent()) ?? "").replace(/,/g, ""));
  await w.click();
  await expect(page.getByTestId("package-list-count")).toHaveText(`${m.toLocaleString("en-US")} package${m === 1 ? "" : "s"}`);
  await expect(page.getByTestId("package-list").getByText("Data last updated")).toHaveCount(0);
  await expect(page.getByTestId("data-updated").first()).toContainText("(simulated)");
});

test("stow: the fingers table renders and rebalances", async ({ page, request }) => {
  await pitchDay(request, 420);
  await page.goto("/stow");
  const fingers = page.getByTestId("stow-fingers");
  await expect(fingers).toContainText("FINGER-A");
  await expect(page.getByTestId("stow-clusters")).toContainText("Minutes of work");
  await page.getByTestId("rebalance-FINGER-A").click();
  await expect(fingers.getByRole("status")).toContainText(/rebalanced|no-op/);
});

test("plan vs. actual: the interval toggle regroups the grid", async ({ page, request }) => {
  await pitchDay(request, 420);
  await page.goto("/plan-vs-actual");
  await expect(page.getByRole("heading", { level: 1, name: "Plan vs. Actual" })).toBeVisible();
  const cols = page.getByTestId("pva-col");
  await expect(page.getByTestId("pva-grid")).toContainText("Induct actual");
  const hourly = await cols.count();
  expect(hourly).toBeGreaterThan(5);
  await page.getByTestId("interval-toggle").getByRole("button", { name: "15 min" }).click();
  await expect.poll(() => cols.count()).toBeGreaterThan(hourly * 3);
  await page.getByTestId("interval-toggle").getByRole("button", { name: "Cumulative" }).click();
  await expect(page.getByTestId("pva-grid")).toContainText("Cumulative (running totals)");
  await expect(page.getByTestId("pva-grid")).toContainText("Automation actual");
});

test("shift plan: work groups, hourly grid and VET/VTO opportunities after dispatch", async ({ page, request }) => {
  await pitchDay(request, 930);
  await page.goto("/labor");
  await expect(page.getByRole("heading", { level: 1, name: "Shift Plan" })).toBeVisible();
  await expect(page.getByTestId("work-groups")).toContainText("Single Cycle");
  await expect(page.getByTestId("plan-grid")).toContainText("Total volume");
  await page.getByTestId("plan-grid").getByRole("button", { name: /Sort/ }).click();
  await expect(page.getByTestId("plan-grid")).toContainText(/Auto-scan induct loader/);
  await page.getByRole("button", { name: "Hours" }).click();
  await expect(page.getByTestId("plan-grid").locator("th").last()).toHaveText("Total");
  // post an opportunity through the lever and see it with its sign-up window
  const r = await request.post(`${SID}/actions`, { data: { kind: "post_opportunity", target: "VET", amount: 2, source: "ui" } });
  expect(r.ok()).toBeTruthy();
  expect((await r.json()).effect).toMatch(/VET opportunity posted/);
  const opps = page.getByTestId("opportunities");
  await expect(opps).toContainText("VET");
  await expect(opps).toContainText(/Open|Closed/);
  await expect(page.getByText("Recommendations (assume no more acceptance of submitted opportunities)")).toBeVisible();
  await page.getByRole("tab", { name: "Pre-Shift" }).click();
  await expect(page.getByTestId("labor-plan")).toContainText("CYCLE_1");
});

test("shift rotation: table with filters and a re-run", async ({ page, request }) => {
  test.setTimeout(150_000);
  await pitchDay(request, 1200);
  await page.goto("/rotation");
  await expect(page.getByRole("heading", { level: 1, name: "Shift Rotation" })).toBeVisible();
  const table = page.getByTestId("rotation-table");
  await expect(table).toBeVisible();
  await expect(page.getByTestId("rotation-info")).toContainText(/compliance/);
  await page.getByLabel("Rotation priority filter").selectOption("High");
  await expect(table.locator("tbody tr").first()).toContainText("High");
  await page.getByTestId("rerun-rotation").click();
  await expect(page.getByRole("status").filter({ hasText: /rotation/i }).first()).toBeVisible();
});

test("associates: induct / stow / pick tabs with team aggregates by default", async ({ page, request }) => {
  await pitchDay(request, 420);
  await page.goto("/associates");
  await expect(page.getByRole("heading", { level: 1, name: "Associates" })).toBeVisible();
  await expect(page.getByTestId("assoc-table")).toContainText("All induct");
  await expect(page.getByTestId("governance-note")).toContainText(/aggregates by default/);
  await page.getByRole("tab", { name: "Stow" }).click();
  await expect(page.getByTestId("assoc-table")).toContainText("All stow");
  await page.getByTestId("show-individual").check();
  await expect(page.getByTestId("assoc-table")).toContainText("FSAF DPMO");
  await expect(page.getByTestId("assoc-table")).toContainText(/assoc/);
  await page.getByRole("tab", { name: "Pick" }).click();
  await expect(page.getByText("Without picklist").first()).toBeVisible();
});
