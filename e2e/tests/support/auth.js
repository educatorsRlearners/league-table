// Login helpers shared by the e2e specs. They drive the real login screen.

const { expect } = require("@playwright/test");

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

module.exports = { loginAsStudent, loginAsInstructor, logout };
