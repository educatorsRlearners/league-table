const { compose, waitUntilHealthy } = require("./compose");

module.exports = async function globalSetup() {
  compose("up", "-d", "--build");
  await waitUntilHealthy();
};
