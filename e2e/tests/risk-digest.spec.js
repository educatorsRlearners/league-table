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

  test("Escape closes the risk record from inside the note box without saving the draft", async ({ page }) => {
    await page.getByRole("button", { name: new RegExp(`^${FLAGGED_STUDENT}`) }).click();
    const record = page.getByRole("dialog", { name: "Risk record" });
    const box = record.getByRole("textbox", { name: "Log outreach" });
    await box.fill("Unsent draft");
    await expect(box).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(record).toHaveCount(0);
    await expect(page.getByText("Unsent draft")).toHaveCount(0);
  });

  test("closing the risk record while a note is still saving does not reopen it", async ({ page }) => {
    // Hold the save back so the record is closed before the response arrives.
    await page.route("**/students/*/notes", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 600));
      await route.continue();
    });

    await page.getByRole("button", { name: new RegExp(`^${FLAGGED_STUDENT}`) }).click();
    const record = page.getByRole("dialog", { name: "Risk record" });
    await record.getByRole("textbox", { name: "Log outreach" }).fill(`Slow save (${Date.now()})`);
    await record.getByRole("button", { name: "Save note" }).click();
    await page.keyboard.press("Escape");
    await expect(record).toHaveCount(0);

    // Wait out the held-back save and the refresh that follows it; the record must stay closed.
    await expect(page.getByRole("button", { name: new RegExp(`^${FLAGGED_STUDENT}.*\\d+ notes?`) })).toBeVisible();
    await expect(record).toHaveCount(0);
  });

  test("a note logged in the risk record is kept for the instructor and never shown to the student", async ({ page }) => {
    const note = `Spoke after class about attendance (${Date.now()})`;

    await page.getByRole("button", { name: new RegExp(`^${FLAGGED_STUDENT}`) }).click();
    const record = page.getByRole("dialog", { name: "Risk record" });
    const box = record.getByRole("textbox", { name: "Log outreach" });
    await box.fill(note);
    await record.getByRole("button", { name: "Save note" }).click();
    // The box clears once the note is saved; the text is also mirrored in the box until then.
    await expect(box).toHaveValue("");
    await expect(record.getByText(note)).toBeVisible();

    // Escape closes the record even while the note box has focus.
    await page.keyboard.press("Escape");
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
