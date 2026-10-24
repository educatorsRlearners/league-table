// The instructor's league table: ranking, view controls, the score breakdown
// drawer, class switching and Present mode. Assertions are structural rather
// than exact scores, because commitment-approvals.spec.js changes s01 and s02's
// baselines and the specs share one database.

const { test, expect } = require("@playwright/test");
const { loginAsInstructor } = require("./support/auth");

const rankingRows = (page) => page.locator('[data-open-key^="row:"]');

test.describe("league table", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsInstructor(page);
  });

  test("ranks the top ten, reveals the whole class, and keeps ranks in order", async ({ page }) => {
    await expect(rankingRows(page)).toHaveCount(10);

    await page.getByRole("button", { name: /^Show all \d+$/ }).click();
    await expect(rankingRows(page)).toHaveCount(24);

    const labels = await rankingRows(page).evaluateAll((rows) => rows.map((r) => r.getAttribute("aria-label")));
    const ranks = labels.map((label) => Number(label.match(/^Rank (\d+),/)[1]));
    expect(ranks[0]).toBe(1);
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
  });

  test("opens a student's score breakdown and closes it with Escape", async ({ page }) => {
    const first = rankingRows(page).first();
    const label = await first.getAttribute("aria-label");
    const name = label.match(/^Rank \d+, (.+?), score/)[1];

    await first.click();
    const drawer = page.getByRole("dialog", { name: "Score breakdown" });
    await expect(drawer.getByRole("heading", { name })).toBeVisible();
    await expect(drawer.getByRole("columnheader", { name: "Criterion" })).toBeVisible();
    await expect(drawer.getByRole("cell", { name: "Homework" })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
  });

  test("window and criteria controls change what the table is ranked on", async ({ page }) => {
    await expect(page.getByText(/Rolling 4 weeks to week 16/)).toBeVisible();

    await page.getByRole("button", { name: "Cumulative" }).click();
    await expect(page.getByText(/Weeks 1–16 cumulative/)).toBeVisible();

    await page.getByRole("button", { name: "Week", exact: true }).click();
    await expect(page.getByText(/\bWeek 16\. Ranked on/)).toBeVisible();

    await page.keyboard.press("1");
    await expect(page.getByText(/ 1 of 5 criteria/)).toBeVisible();
    await page.keyboard.press("0");
    await expect(page.getByText(/ 5 of 5 criteria/)).toBeVisible();
  });

  test("stepping back a week moves the table to the earlier week", async ({ page }) => {
    await expect(page.getByText("Week 16", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Previous week" }).click();
    await expect(page.getByText("Week 15", { exact: true })).toBeVisible();
  });

  test("switches class", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1, name: "PHYS 204 · Mechanics" })).toBeVisible();
    await page.getByRole("button", { name: "DATA 118" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /^DATA 118/ })).toBeVisible();
    await expect(rankingRows(page).first()).toBeVisible();
  });

  test("Present mode hides the instructor-only screens until it is exited", async ({ page }) => {
    await expect(page.getByRole("button", { name: "Risk digest" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Approvals" })).toBeVisible();

    await page.getByRole("button", { name: "Present" }).click();
    await expect(page.getByRole("button", { name: "Risk digest" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Approvals" })).toHaveCount(0);

    await page.keyboard.press("p");
    await expect(page.getByRole("button", { name: "Risk digest" })).toBeVisible();
  });
});
