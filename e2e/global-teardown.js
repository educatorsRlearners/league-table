const { compose } = require("./compose");

module.exports = async function globalTeardown() {
  compose("down", "-v");
};
