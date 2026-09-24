// Points Playwright at an already-installed Chromium-based browser (Brave)
// instead of downloading Playwright's own ~180MB copy of Chromium. Brave
// speaks the same DevTools protocol Playwright automates over, so this works
// like Playwright's built-in `channel: 'chrome'` support for Google Chrome,
// just via `executablePath` since Brave isn't one of Playwright's named
// channels.
//
// Falls back to Playwright's bundled Chromium (via `npx playwright install
// chromium`) when no Brave install is found - e.g. on a CI box.

const fs = require("node:fs");

const CANDIDATE_PATHS = [
  process.env.BRAVE_PATH,
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", // macOS
  "/usr/bin/brave-browser", // Linux (most distro packages)
  "/usr/bin/brave", // Linux (some distros)
  "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe", // Windows
].filter(Boolean);

function findBrave() {
  return CANDIDATE_PATHS.find((p) => fs.existsSync(p));
}

module.exports = { findBrave };
