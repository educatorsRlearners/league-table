// The instructor's risk digest and risk record, including the guarantee that a
// note left there never reaches the student it is about.

const { test, expect } = require("@playwright/test");
const { loginAsInstructor, loginAsStudent, logout } = require("./support/auth");

// Seeded as "High risk" in PHYS 204: downward trend, low engagement and low projected grade.
const FLAGGED_STUDENT = "Jonas Reuter";
const FLAGGED_STUDENT_ID = "s10";

test.describe("risk digest", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsInstructor(page);
    await page.getByRole("button", { name: "Risk digest" }).click();
  });

  test("groups flagged students by class", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 2, name: "Digest" })).toBeVisible();
    await expect(page.getByText(/Evaluated at week 16, compared with week 15/)).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: "PHYS 204 · Mechanics" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: /^DATA 118/ })).toBeVisible();

    const flagged = page.getByRole("button", { name: new RegExp(`^${FLAGGED_STUDENT} High risk`) });
    await expect(flagged).toBeVisible();
    await expect(flagged).toContainText("Downward trend");
  });

  test("opens a risk record showing each signal and the data behind it", async ({ page }) => {
    await page.getByRole("button", { name: new RegExp(`^${FLAGGED_STUDENT}`) }).click();

    const record = page.getByRole("dialog", { name: "Risk record" });
    await expect(record.getByRole("heading", { level: 2, name: FLAGGED_STUDENT })).toBeVisible();
    await expect(record.getByText("High risk")).toBeVisible();
    await expect(record.getByText("Downward trend")).toBeVisible();
    await expect(record.getByText(/The weighted score has fallen \d+ weeks running\./)).toBeVisible();
    await expect(record.getByText("Attendance to date")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(record).toHaveCount(0);
  });

  test("a note logged in the risk record is kept for the instructor and never shown to the student", async ({ page }) => {
    const note = `Spoke after class about attendance (${Date.now()})`;

    await page.getByRole("button", { name: new RegExp(`^${FLAGGED_STUDENT}`) }).click();
    const record = page.getByRole("dialog", { name: "Risk record" });
    await record.getByRole("textbox", { name: "Log outreach" }).fill(note);
    await record.getByRole("button", { name: "Save note" }).click();
    await expect(record.getByText(note)).toBeVisible();

    // Escape is ignored while the note box has focus, so close with the button.
    await record.getByRole("button", { name: "Close" }).click();
    await expect(record).toHaveCount(0);
    await expect(page.getByRole("button", { name: new RegExp(`^${FLAGGED_STUDENT}.*\\d+ notes?`) })).toBeVisible();
    await logout(page);

    await loginAsStudent(page, { classId: "c1", studentId: FLAGGED_STUDENT_ID });
    for (const tab of ["My breakdown", "My standing", "My commitments"]) {
      await page.getByRole("button", { name: tab }).click();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText(note)).toHaveCount(0);
    }
  });
});
