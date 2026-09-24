const { defineConfig } = require("@playwright/test");
const { BASE_URL } = require("./compose");
const { findBrave } = require("./browser");

const bravePath = findBrave();

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  globalSetup: require.resolve("./global-setup"),
  globalTeardown: require.resolve("./global-teardown"),
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    ...(bravePath ? { launchOptions: { executablePath: bravePath } } : {}),
  },
});
