// Shared helpers for driving the docker-compose stack these e2e tests run
// against. The stack runs as its own compose project with remapped host
// ports (docker-compose.e2e.yml), so it never collides with a stack you
// already have running via plain `docker compose up`, or with the Python
// integration tests' stack (docker-compose.integration.yml).

const { execFileSync } = require("node:child_process");
const path = require("node:path");

const REPO_ROOT = path.resolve(__dirname, "..");
const PROJECT = "league_table_e2e";
const COMPOSE_ARGS = [
  "compose",
  "-p", PROJECT,
  "-f", path.join(REPO_ROOT, "docker-compose.yml"),
  "-f", path.join(REPO_ROOT, "docker-compose.e2e.yml"),
];

const BASE_URL = "http://localhost:18010";

function compose(...args) {
  return execFileSync("docker", [...COMPOSE_ARGS, ...args], {
    cwd: REPO_ROOT,
    stdio: "inherit",
  });
}

async function waitUntilHealthy(timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE_URL}/login/options`);
      if (res.ok) return;
      lastError = `status ${res.status}`;
    } catch (err) {
      lastError = err;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`backend never became healthy at ${BASE_URL}: ${lastError}`);
}

module.exports = { compose, waitUntilHealthy, BASE_URL, PROJECT };
