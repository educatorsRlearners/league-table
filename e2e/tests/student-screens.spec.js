// What a student sees, and what the API refuses to show them. Rosa Ibarra (s18)
// is seeded "At risk" and has not entered a baseline, so her pages are stable.

const { test, expect } = require("@playwright/test");
const { loginAsStudent } = require("./support/auth");

const STUDENT = { classId: "c1", studentId: "s18" };
const STUDENT_NAME = "Rosa Ibarra";
const CLASSMATE_ID = "s07";
const WEEK_ID = "w16";

const asStudent = (studentId) => ({ headers: { Authorization: `Bearer ${studentId}` } });

test.describe("student screens", () => {
  test("a student gets their own three screens and none of the instructor's", async ({ page }) => {
    await loginAsStudent(page, STUDENT);

    const screens = page.getByRole("navigation", { name: "Screens" });
    for (const tab of ["My breakdown", "My standing", "My commitments"]) {
      await expect(screens.getByRole("button", { name: tab })).toBeVisible();
    }
    for (const tab of ["League table", "Risk digest", "Approvals"]) {
      await expect(screens.getByRole("button", { name: tab })).toHaveCount(0);
    }
  });

  test("My breakdown shows the student's own rank and criteria", async ({ page }) => {
    await loginAsStudent(page, STUDENT);

    await expect(page.getByRole("heading", { level: 2, name: STUDENT_NAME })).toBeVisible();
    await expect(page.getByText("Only you can see this", { exact: false })).toBeVisible();
    await expect(page.getByText("in this class")).toBeVisible();
    await expect(page.getByRole("cell", { name: "Homework" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Quizzes" })).toBeVisible();
  });

  test("My standing shows the student's level, the signals behind it and where to get help", async ({ page }) => {
    await loginAsStudent(page, STUDENT);
    await page.getByRole("button", { name: "My standing" }).click();

    await expect(page.getByText("Where you stand")).toBeVisible();
    await expect(page.getByText("At risk", { exact: true })).toBeVisible();
    await expect(page.getByText("Missed or low engagement")).toBeVisible();
    await expect(page.getByText(/Office hours are Tuesdays/)).toBeVisible();
    await expect(page.getByText(/never appears on the league table/)).toBeVisible();
  });

  test("the API gives a student only their own detail", async ({ request, baseURL }) => {
    const own = asStudent(STUDENT.studentId);

    // Another student's breakdown, standing, risk record and commitments are refused.
    const refused = [
      `/classes/c1/students/${CLASSMATE_ID}/explanation?week=${WEEK_ID}`,
      `/me/standing?classId=c1&studentId=${CLASSMATE_ID}`,
      `/classes/c1/students/${CLASSMATE_ID}/risk`,
      `/me/commitments?classId=c1&studentId=${CLASSMATE_ID}`,
    ];
    for (const path of refused) {
      const res = await request.get(`${baseURL}${path}`, own);
      expect(res.status(), path).toBe(403);
    }

    // The class-wide ranking shows classmates' rank and score but not their raw score, factor or hours.
    const ranking = await request.get(`${baseURL}/classes/c1/ranking?week=${WEEK_ID}`, own);
    expect(ranking.ok()).toBeTruthy();
    const { rows } = await ranking.json();
    const self = rows.find((r) => r.is_self);
    expect(self.student_id).toBe(STUDENT.studentId);
    expect(self).toHaveProperty("raw");
    const classmates = rows.filter((r) => !r.is_self);
    expect(classmates.length).toBeGreaterThan(0);
    for (const row of classmates) {
      expect(row).toHaveProperty("rank");
      expect(row).toHaveProperty("score");
      for (const field of ["raw", "factor", "weighted_hours", "hours_source"]) {
        expect(row, `${row.student_id}.${field}`).not.toHaveProperty(field);
      }
    }
  });

  test("a student cannot reach instructor-only endpoints", async ({ request, baseURL }) => {
    const own = asStudent(STUDENT.studentId);
    for (const path of ["/instructor/digest", "/classes/c1/commitments/pending", "/classes/c1/risk-settings"]) {
      const res = await request.get(`${baseURL}${path}`, own);
      expect(res.status(), path).toBe(403);
    }
  });
});
