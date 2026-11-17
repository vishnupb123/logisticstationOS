// v2 shell: settings, "How this is calculated" drawers, the unified work-item
// inbox, presenter chapters + the global cycle banner, and the shift report.
// Runs against the real stack; every session is simulated.
import type { APIRequestContext } from "@playwright/test";
import { expect, test } from "./fixtures.ts";

const API = process.env.E2E_API_URL ?? "http://localhost:8010";

async function newDay(request: APIRequestContext, preset: string, speed: number, mode = "autopilot", seed = 3) {
  const r = await request.post(`${API}/runtime/sessions`, { data: { preset, seed, speed, mode } });
  expect(r.ok()).toBeTruthy();
}

async function seek(request: APIRequestContext, minute: number) {
  const r = await request.post(`${API}/runtime/sessions/default/seek`, { data: { minute } });
  expect(r.ok()).toBeTruthy();
}

async function settingsValue(request: APIRequestContext, key: string) {
  const r = await request.get(`${API}/runtime/sessions/default/state`);
  return (await r.json()).views.settings.values[key];
}

test.describe("settings", () => {
  // the invalid save is expected to fail with a 422 the page surfaces
  test.use({ allowedConsoleErrors: [/422/] });

  test("save round-trips and a bad value shows the server's error", async ({ page, request }) => {
    await newDay(request, "normal_day", 2);
    await page.goto("/settings");
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    await expect(page.getByTestId("site-profile")).toContainText("pick start");
    const dwell = page.getByTestId("setting-induct_dwell_minutes");
    await dwell.fill("75");
    await page.getByTestId("settings-save").click();
    await expect(page.getByTestId("settings-saved")).toBeVisible();
    await expect.poll(() => settingsValue(request, "induct_dwell_minutes")).toBe(75);
    await expect(dwell).toHaveValue("75");

    await page.getByTestId("setting-stow_wip_lower_min").fill("45");
    await page.getByTestId("settings-save").click();
    await expect(page.getByTestId("settings-error")).toContainText("422");
    expect(await settingsValue(request, "stow_wip_lower_min")).toBe(15);
  });
});

test("metric drawer explains Stow WIP as a documented formula", async ({ page, request }) => {
  await newDay(request, "normal_day", 5);
  await page.goto("/command");
  await page.getByTestId("metric-info-stow_wip_minutes").click();
  const drawer = page.getByTestId("metric-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("How this is calculated");
  await expect(drawer.getByTestId("provenance-badge")).toContainText("documented");
  await expect(drawer).toContainText("inc pending stow");
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(page.getByTestId("data-updated").first()).toContainText("Data last updated");
});

test("work items: complete and dismiss from the unified inbox", async ({ page, request }) => {
  await newDay(request, "pitch_day", 5, "advise");
  await request.post(`${API}/runtime/sessions/default/control`, { data: { speed: 1 } });
  await seek(request, 600);
  await page.goto("/work-items");
  await expect(page.getByRole("heading", { level: 1, name: "Work Items" })).toBeVisible();
  const inbox = page.getByTestId("work-item-inbox");
  await expect(inbox).toBeVisible();
  const completed = page.getByTestId("wi-completed");
  const before = Number(await completed.textContent());

  const complete = inbox.locator('[data-testid^="wi-complete-"]').first();
  await expect(complete).toBeVisible();
  await complete.click();
  await expect.poll(async () => Number(await completed.textContent())).toBeGreaterThan(before);

  const dismiss = inbox.locator('[data-testid^="wi-dismiss-"]').first();
  if (await dismiss.count()) {
    const id = ((await dismiss.getAttribute("data-testid")) ?? "").replace("wi-dismiss-", "");
    await dismiss.click();
    await expect(page.getByTestId(`wi-dismiss-${id}`)).toHaveCount(0);
    if (id.startsWith("WI-")) {
      // (a dismissed agent recommendation leaves the list entirely; a plain work item stays as "dismissed")
      await page.getByLabel("Filter by state").selectOption("dismissed");
      await expect(page.getByTestId("work-items-table")).toContainText("dismissed");
    }
  }
  // the bell links to the inbox
  await page.getByTestId("notification-bell").click();
  await expect(page.getByTestId("bell-work-items")).toContainText("pending work item");
});

test("pitch day: chapter jump to 10:00 raises the cycle banner and force induct applies", async ({ page, request }) => {
  await newDay(request, "pitch_day", 5, "advise");
  await page.goto("/command");
  await expect(page.getByTestId("presenter-bar")).toBeVisible();
  await page.getByTestId("chapter-600").click();
  await expect(page.getByTestId("sim-clock-global")).toHaveText(/^1[0-9]:/, { timeout: 15_000 });
  const banner = page.getByTestId("cycle-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText(/pick has been started/i);
  await expect(banner).toContainText("on floor, missed cycle");
  await page.getByTestId("cycle-force-induct").click();
  await expect(page.getByTestId("cycle-effect")).toBeVisible();
  await expect(page.getByTestId("cycle-effect")).not.toContainText(/error|failed/i);
  await expect
    .poll(async () => {
      const r = await request.get(`${API}/runtime/sessions/default/state`);
      const v = (await r.json()).views.cycles;
      return v.changes.some((c: { action: string }) => c.action === "force_induct");
    })
    .toBe(true);
});

test("presenter mode toggles large type", async ({ page }) => {
  await page.goto("/command");
  await page.getByTestId("presenter-toggle").click();
  await expect(page.locator("body")).toHaveClass(/presenter-mode/);
  await page.getByTestId("presenter-toggle").click();
  await expect(page.locator("body")).not.toHaveClass(/presenter-mode/);
});

test("shift report renders, watermarked as simulated", async ({ page }) => {
  await page.goto("/report");
  await expect(page.getByRole("heading", { level: 1, name: "Shift report" })).toBeVisible();
  await expect(page.getByTestId("shift-report")).toBeVisible();
  await expect(page.getByTestId("report-simulated")).toContainText("SIMULATED");
  await expect(page.getByTestId("report-print")).toBeVisible();
});

test("v2 pages have no horizontal overflow at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/command", "/work-items", "/settings", "/report"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate<number>("document.documentElement.scrollWidth - document.documentElement.clientWidth");
    expect(overflow, `${path} overflows`).toBeLessThanOrEqual(0);
  }
});
