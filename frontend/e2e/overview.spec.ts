import { expect, test } from "./fixtures.ts";

test("overview shows end-to-end funnel and stage cycle times from the analytics pipeline", async ({
  page,
}) => {
  await page.goto("/");
  const inducted = page.getByTestId("kpi-inducted");
  await expect(inducted).toBeVisible();
  const value = Number((await inducted.locator(".kpi__value").innerText()).replace(/,/g, ""));
  expect(value).toBeGreaterThan(0);
  // The funnel's first stage agrees with the KPI tile (two different endpoints).
  await expect(page.getByTestId("funnel-inducted")).toContainText(value.toLocaleString());
  await expect(page.getByRole("cell", { name: "Induct → stow" })).toBeVisible();
  await expect(page.getByTestId("refresh-meta")).toContainText(/Updated|Refreshing/);
});
