// The live station end to end: a running simulated day shared by every page,
// agents acting on it, the chat assistant, DSP coordination, pick
// prioritisation, scrubs, copilot approvals, close-out, the next day from the
// final truckfile, and the assistant's explanations.
import type { APIRequestContext, Page } from "@playwright/test";
import { expect, test } from "./fixtures.ts";

const API = process.env.E2E_API_URL ?? "http://localhost:8010";

async function newDay(request: APIRequestContext, preset: string, speed: number, mode = "autopilot", seed = 7) {
  const r = await request.post(`${API}/runtime/sessions`, { data: { preset, seed, speed, mode } });
  expect(r.ok()).toBeTruthy();
}

async function waitForClock(page: Page, hhmm: string, timeout = 60_000) {
  const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
  await expect
    .poll(async () => toMin((await page.getByTestId("sim-clock-global").textContent()) ?? "00:00"), { timeout })
    .toBeGreaterThanOrEqual(toMin(hhmm));
}

test("the session bar shows a live, advancing simulated day and can start a new one", async ({ page, request }) => {
  await newDay(request, "normal_day", 5);
  await page.goto("/command");
  const clock = page.getByTestId("sim-clock-global");
  await expect(clock).toBeVisible();
  const first = await clock.textContent();
  await expect.poll(async () => clock.textContent(), { timeout: 15_000 }).not.toBe(first);
  await page.getByTestId("new-day").click();
  await page.getByLabel("New day scenario").selectOption("induct_line_outage");
  await page.getByLabel("New day seed").fill("3");
  await page.getByTestId("start-new-day").click();
  await expect(page.getByTestId("session-bar")).toContainText(/induct line outage · seed 3/i);
  await expect(page.getByTestId("kpi-dea")).toBeVisible();
});

test("chat answers from live state and acts on the simulated station", async ({ page, request }) => {
  await newDay(request, "induct_line_outage", 20);
  await page.goto("/assistant");
  const input = page.getByLabel("Message the station assistant");
  await input.fill("status");
  await input.press("Enter");
  await expect(page.getByTestId("chat-assistant").last()).toContainText("DEA");
  await input.fill("simulate a jam on line 2 for 20 min");
  await input.press("Enter");
  await expect(page.getByTestId("chat-assistant").last()).toContainText("L2 jammed");
  await input.fill("what if we vet 2 stowers");
  await input.press("Enter");
  await expect(page.getByTestId("chat-assistant").last()).toContainText("not applied", { timeout: 60_000 });
  await page.getByTestId("chat-launcher").click();
  await expect(page.getByRole("dialog", { name: "Station assistant" })).toBeVisible();
});

test("dispatch coordination: DSPs, drivers, map and one-click actions", async ({ page, request }) => {
  await newDay(request, "dispatch_disruption", 60, "observe");
  await page.goto("/dispatch");
  await waitForClock(page, "08:00");
  await expect(page.getByTestId("dsp-table")).toContainText("DSP-DELTA");
  await expect(page.getByTestId("driver-map")).toBeVisible();
  await page.getByTestId("notify-late").click();
  await expect(page.getByRole("status").filter({ hasText: /notified/ }).first()).toBeVisible();
});

test("pick prioritisation and ageing scrub act on the live station", async ({ page, request }) => {
  await newDay(request, "normal_day", 5);
  await page.goto("/pick");
  await page.getByTestId("prio-R-080").click();
  await expect(page.getByRole("status").filter({ hasText: /R-080 prioritised/ })).toBeVisible();
  await page.goto("/packages?tab=ageing");
  await page.getByTestId("scrub-in-station").click();
  await expect(page.getByRole("status").filter({ hasText: /scrub/ }).first()).toBeVisible();
  await page.getByTestId("review-missing").click();
  await expect(page.getByRole("heading", { name: "Missing packages" })).toBeVisible();
});

test("copilot mode queues agent recommendations that a human approves", async ({ page, request }) => {
  await newDay(request, "induct_line_outage", 20, "advise");
  await page.goto("/agent");
  await expect(page.getByTestId("pending-recs")).toBeVisible({ timeout: 90_000 });
  const approve = page.getByTestId("pending-recs").getByRole("button", { name: "Approve" }).first();
  await approve.click();
  await expect(page.getByTestId("agent-action-log")).toContainText("Applied in twin", { timeout: 15_000 });
  await page.getByTestId("mode-autopilot").click();
  await expect(page.getByTestId("session-bar")).toContainText(/Agents: autopilot|induct line outage/i);
});

test("live pages render their tables", async ({ page, request }) => {
  await newDay(request, "peak_volume", 60, "observe");
  await page.goto("/high-value");
  await waitForClock(page, "07:00");
  await expect(page.getByTestId("hv-flow")).toBeVisible();
  for (const [path, id] of [
    ["/associates", "assoc-table"],
    ["/labor", "labor-plan"],
    ["/stow", "stow-buffers"],
    ["/induct", "sort-hourly"],
    ["/inbound", "receive-overall"],
    ["/stage", "staging-floor"],
    ["/outbound", "wave-grid"],
    ["/station", "layout-aisles"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByTestId(id)).toBeVisible();
  }
});

test("station agent investigation flows into approval and observed outcome", async ({ page }) => {
  test.setTimeout(330_000); // v2 model: heavier counterfactual planning per investigation
  await page.goto("/agent/investigations");
  await page.getByLabel("Scenario").selectOption("induct_line_outage");
  await page.getByLabel("Investigate up to").selectOption("420");
  await page.getByTestId("sa-run").click();
  await expect(page.getByTestId("exec-status")).toHaveText(/completed|degraded/, { timeout: 300_000 });
  await expect(page.getByTestId("exec-findings")).toContainText("recommend");
  await page.getByTestId("exec-decisions").getByRole("link").first().click();
  await expect(page.getByRole("heading", { level: 1, name: "station_ops_mitigation" })).toBeVisible();
  await page.getByLabel("Acting as").fill("e2e supervisor");
  await page.getByLabel("Role").selectOption("supervisor");
  await page.getByLabel("Selected candidate (for approval)").selectOption({ index: 1 });
  await page.getByLabel("Rationale").fill("e2e approval of the simulated plan");
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Observe outcome" }).click();
  await expect(page.getByTestId("observed-outcome")).toContainText("fresh seed");
});

test("live staging floor plan and aisle plan show the pick floor, with click-through detail", async ({ page, request }) => {
  await newDay(request, "normal_day", 60, "observe", 2);
  await page.goto("/stage");
  await waitForClock(page, "09:15", 90_000);
  await expect(page.getByTestId("staging-floor")).toBeVisible();
  await expect(page.getByTestId("wave-strip")).toContainText("W1");
  await page.getByTestId("slot-STG-A01").click();
  await expect(page.getByTestId("slot-detail")).toContainText("R-001");
  await page.goto("/pick");
  await page.getByTestId("aisle-plan-toggle").click();
  await expect(page.getByTestId("aisle-plan")).toBeVisible();
  await page.getByTestId("aisle-A01").click();
  await expect(page.getByTestId("aisle-detail")).toContainText("Aisle A01");
});

test("yard VSA, DSP comms and the notification centre", async ({ page, request }) => {
  await newDay(request, "normal_day", 60, "observe", 2);
  await page.goto("/dispatch");
  await waitForClock(page, "10:30", 90_000);
  await page.getByRole("tab", { name: "Yard · VSA" }).click();
  await expect(page.getByTestId("vsa-table")).toContainText(/pass/);
  await page.getByRole("tab", { name: "DSP comms" }).click();
  await expect(page.getByTestId("notification-list")).toBeVisible();
  await page.getByTestId("notification-bell").click();
  const dialog = page.getByRole("dialog", { name: "Notifications" });
  await expect(dialog).toContainText(/Wrong staging scan|Van grounded|bag/i);
  await dialog.getByRole("button", { name: "Acknowledge all" }).click();
  await expect(dialog.getByRole("button", { name: "Acknowledge", exact: true })).toHaveCount(0);
});

test("after dispatch: close-out tasks, tomorrow's truckfile and plan", async ({ page, request }) => {
  await newDay(request, "normal_day", 60, "observe", 2);
  await page.goto("/closeout");
  await expect(page.getByTestId("tasks-supervisor")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("tasks-supervisor")).toContainText(/GTDR|ferry|Floor close/);
  await page.getByTestId("co-check-ferry").click();
  await expect(page.getByRole("status").filter({ hasText: /ferry check/ }).first()).toBeVisible();
  await page.getByRole("tab", { name: "Truckfile" }).click();
  await expect(page.getByTestId("tomorrow-truckfile")).toContainText("PORT-X1");
  await page.getByRole("tab", { name: "Scrubs & sweep" }).click();
  await expect(page.getByTestId("sweep-log")).toBeVisible();
});

test("the next day runs from the final truckfile, and the assistant explains the shift with sources", async ({ page, request }) => {
  await newDay(request, "ferry_disruption", 60, "observe", 2);
  await page.goto("/closeout");
  await expect(page.getByTestId("run-next-day")).toBeVisible({ timeout: 120_000 });
  await page.goto("/assistant");
  const input = page.getByLabel("Message the station assistant");
  await input.fill("why did DEA drop?");
  await input.press("Enter");
  const answer = page.getByTestId("chat-assistant").last();
  await expect(answer).toContainText("Where the misses came from", { timeout: 90_000 });
  await expect(answer).toContainText(/Sources \(\d+\)/);
  await input.fill("status of the trucks and ferries");
  await input.press("Enter");
  await expect(page.getByTestId("chat-assistant").last()).toContainText("Tomorrow's truckfile", { timeout: 90_000 });
  await page.goto("/closeout");
  await page.getByTestId("run-next-day").click();
  await expect(page.getByTestId("session-bar")).toContainText("Day 2", { timeout: 30_000 });
  await expect(page.getByTestId("session-bar")).toContainText(/truckfile v\d/);
});
