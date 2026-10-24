// Runs the frontend scoring, risk and mock-client suites (frontend/services/tests.js)
// headlessly under Node. Prints each failing test and exits 1 if any fail.
// Tests.dc.html runs the same suites in a browser.

import { runAll } from '../frontend/services/tests.js';

const results = await runAll();

let passed = 0;
const failures = [];
for (const suite of results) {
  for (const test of suite.cases) {
    if (test.pass) passed += 1;
    else failures.push(`${suite.name} › ${test.title}: ${test.error}`);
  }
}

for (const line of failures) console.error(`FAIL ${line}`);
console.log(`${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
