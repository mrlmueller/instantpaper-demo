import { expect, test, type Page } from "@playwright/test";

const richRun = "ca79147de41f8edbfb47c9e5";
const partialRun = "17d29aaee1fecc8cf1a34025";
const largeRun = "4af2666be828e5054ccf4d31";

async function capture(page: Page, url: string, outputPath: string) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => {
    pageErrors.push(String(error));
  });

  await page.goto(url);
  await page.waitForSelector(".hero-title");
  await page.waitForTimeout(1200);
  expect(pageErrors, `page errors for ${url}`).toEqual([]);
  expect(consoleErrors, `console errors for ${url}`).toEqual([]);
  await page.screenshot({ fullPage: true, path: outputPath });
}

test("rich overview", async ({ page }) => {
  await capture(page, `/?run=${richRun}&tab=overview`, "test-results/01-rich-overview.png");
});

test("plan view", async ({ page }) => {
  await capture(page, `/?run=${richRun}&tab=plan`, "test-results/02-plan-view.png");
});

test("queries view", async ({ page }) => {
  await capture(page, `/?run=${richRun}&tab=queries`, "test-results/02b-queries-view.png");
});

test("scoring view", async ({ page }) => {
  await capture(page, `/?run=${richRun}&tab=scoring`, "test-results/03-scoring-view.png");
});

test("coverage view", async ({ page }) => {
  await capture(page, `/?run=${richRun}&tab=coverage`, "test-results/03a-coverage-view.png");
});

test("candidate view", async ({ page }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => {
    pageErrors.push(String(error));
  });

  await page.goto(`/?run=${richRun}&tab=candidates`);
  await page.waitForSelector(".hero-title");
  await page.waitForTimeout(1200);
  await page.locator(".candidate-accordion button[data-state='closed']").first().click();
  await page.waitForTimeout(500);
  expect(pageErrors, "page errors for candidate view").toEqual([]);
  expect(consoleErrors, "console errors for candidate view").toEqual([]);
  await page.screenshot({ fullPage: true, path: "test-results/03b-candidate-view.png" });
});

test("rerank view", async ({ page }) => {
  await capture(page, `/?run=${richRun}&tab=rerank`, "test-results/03bb-rerank-view.png");
});

test("final view", async ({ page }) => {
  await capture(page, `/?run=${richRun}&tab=final`, "test-results/03c-final-view.png");
});

test("partial overview", async ({ page }) => {
  await capture(page, `/?run=${partialRun}&tab=overview`, "test-results/04-partial-overview.png");
});

test("large overview", async ({ page }) => {
  await capture(page, `/?run=${largeRun}&tab=overview`, "test-results/05-large-overview.png");
});

test("compare view", async ({ page }) => {
  await capture(page, `/?run=${richRun}&compare=${largeRun}&tab=compare`, "test-results/06-compare-view.png");
});

test("heavy run switch", async ({ page }) => {
  await capture(page, `/?run=25e6243ac55a5904fb1fcdfe&tab=overview`, "test-results/07-heavy-run-overview.png");
  await capture(page, `/?run=0eb47e270f7586fd6f09795c&tab=overview`, "test-results/08-second-heavy-run-overview.png");
});
