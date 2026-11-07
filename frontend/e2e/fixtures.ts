import { test as base, expect } from "@playwright/test";

// Every test fails if the page logs a console error or throws — the
// class of regression the original scratch verification caught by eye.
// A test that *expects* a specific error (e.g. a 403 the UI is meant to
// surface) declares it with `test.use({ allowedConsoleErrors: [...] })`.
export const test = base.extend<{ allowedConsoleErrors: RegExp[]; consoleErrors: string[] }>({
  allowedConsoleErrors: [[], { option: true }],
  consoleErrors: [
    async ({ page, allowedConsoleErrors }, use) => {
      const errors: string[] = [];
      const record = (text: string) => {
        if (!allowedConsoleErrors.some((re) => re.test(text))) errors.push(text);
      };
      page.on("console", (m) => {
        if (m.type() === "error") record(m.text());
      });
      page.on("pageerror", (e) => record(String(e)));
      await use(errors);
      expect(errors, "console/page errors").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
