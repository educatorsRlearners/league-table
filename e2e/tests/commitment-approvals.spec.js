// End-to-end test against the real docker-compose stack (real browser, real
// FastAPI backend, real Postgres - see ../global-setup.js). Covers the
// baseline-commitment approval workflow end to end:
//
//   1. Two students log in and submit a semester baseline.
//   2. They log out.
//   3. The instructor logs in, approves one baseline and rejects the other,
//      leaving a note explaining the rejection.
//   4. Both students log back in and see the outcome reflected in their own
//      "My commitments" tab.
//
// The two students (Amara Okonkwo / s01 and Ben Halvorsen / s02, both in
// class c1) already have an *approved* baseline from the seeded demo data;
// submitting a new one here creates a fresh *pending* baseline for the
// instructor to decide on, without disturbing anyone else's seeded state.
//
// Notes are explicitly instructor-only in this app ("Private to you. The
// student never sees notes." - see the Risk digest tab), and the note UI is
// only reachable from a student's risk record, which is only linked from the
// digest when that student is currently flagged - not something this test
// can rely on for an arbitrary student. So the note is left via the same
// backend endpoint the UI's "Save note" button calls
// (POST /classes/:classId/students/:studentId/notes), authenticated the same
// way the app itself authenticates an instructor (Bearer i1). Everything
// else - login, submitting hours, approving/rejecting, reading the result -
// goes through the real UI.

const { test, expect } = require("@playwright/test");

const CLASS_ID = "c1";
const APPROVED_STUDENT_ID = "s01";
const APPROVED_STUDENT = "Amara Okonkwo";
const REJECTED_STUDENT_ID = "s02";
const REJECTED_STUDENT = "Ben Halvorsen";
const REJECTION_NOTE = "Rejected: hours look like a data-entry error, please resubmit.";

async function loginAsStudent(page, { classId, studentId }) {
  await page.goto("/");
  await page.getByRole("button", { name: "Student", exact: true }).click();
  await page.locator("#login-class").selectOption(classId);
  await page.locator("#login-student").selectOption(studentId);
  await page.getByRole("button", { name: "Continue as this student" }).click();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
}

async function loginAsInstructor(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Instructor", exact: true }).click();
  await page.getByRole("button", { name: "Continue as instructor" }).click();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
}

async function logout(page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Student", exact: true })).toBeVisible();
}

async function submitBaseline(page, { work, childcare, eldercare }) {
  await page.getByRole("button", { name: "My commitments" }).click();
  await page.locator("#baseline-work").fill(String(work));
  await page.locator("#baseline-childcare").fill(String(childcare));
  await page.locator("#baseline-eldercare").fill(String(eldercare));
  await page.getByRole("button", { name: "Save semester baseline" }).click();
  // The save round-trips through the API and re-renders the status line;
  // wait for the "pending" wording rather than a fixed timeout.
  await expect(page.getByText(/Pending — /)).toBeVisible();
}

/** The Approvals row for a given student: the smallest container that has
 * both their name and the decision buttons. */
function pendingBaselineRow(page, studentName) {
  return page
    .locator("div")
    .filter({ hasText: studentName })
    .filter({ has: page.getByRole("button", { name: "Approve" }) })
    .last();
}

test.describe("commitment approvals", () => {
  test("students submit baselines, instructor decides, students see the outcome", async ({ page, request, baseURL }) => {
    // 1 + 2. Two students log in, submit a baseline, and log out.
    await loginAsStudent(page, { classId: CLASS_ID, studentId: APPROVED_STUDENT_ID });
    await submitBaseline(page, { work: 10, childcare: 2, eldercare: 0 });
    await logout(page);

    await loginAsStudent(page, { classId: CLASS_ID, studentId: REJECTED_STUDENT_ID });
    await submitBaseline(page, { work: 40, childcare: 0, eldercare: 0 });
    await logout(page);

    // 3. Instructor decides: approve one, reject the other.
    await loginAsInstructor(page);
    await page.getByRole("button", { name: "Approvals" }).click();

    await expect(pendingBaselineRow(page, APPROVED_STUDENT)).toBeVisible();
    await pendingBaselineRow(page, APPROVED_STUDENT).getByRole("button", { name: "Approve" }).click();
    await expect(pendingBaselineRow(page, APPROVED_STUDENT)).toHaveCount(0);

    await expect(pendingBaselineRow(page, REJECTED_STUDENT)).toBeVisible();
    await pendingBaselineRow(page, REJECTED_STUDENT).getByRole("button", { name: "Reject" }).click();
    await expect(pendingBaselineRow(page, REJECTED_STUDENT)).toHaveCount(0);

    // Leave a note explaining the rejection - see the module docstring above
    // for why this goes through the API rather than the digest-gated UI.
    const noteResponse = await request.post(
      `${baseURL}/classes/c1/students/${REJECTED_STUDENT_ID}/notes`,
      { headers: { Authorization: "Bearer i1" }, data: { body: REJECTION_NOTE } },
    );
    expect(noteResponse.ok()).toBeTruthy();

    await logout(page);

    // 4. Both students log back in and see the outcome.
    await loginAsStudent(page, { classId: CLASS_ID, studentId: APPROVED_STUDENT_ID });
    await page.getByRole("button", { name: "My commitments" }).click();
    await expect(page.getByText(/^Approved, counting from week \d+\.$/)).toBeVisible();
    await logout(page);

    await loginAsStudent(page, { classId: CLASS_ID, studentId: REJECTED_STUDENT_ID });
    await page.getByRole("button", { name: "My commitments" }).click();
    await expect(page.getByText(/^Rejected\. Submitting a new baseline below will send it to your instructor again\.$/)).toBeVisible();
    // The rejection note is instructor-only and must never reach the student.
    await expect(page.getByText(REJECTION_NOTE)).toHaveCount(0);
    await logout(page);
  });
});
