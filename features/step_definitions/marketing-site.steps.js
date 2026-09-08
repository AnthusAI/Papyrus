const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { Given, Then } = require("@cucumber/cucumber");

const marketingRoot = path.resolve(__dirname, "../../marketing");

function readMarketingPackage() {
  const packagePath = path.join(marketingRoot, "package.json");
  assert.ok(fs.existsSync(packagePath), "Expected the standalone marketing package to exist.");
  return JSON.parse(fs.readFileSync(packagePath, "utf8"));
}

Given("the Papyrus marketing site foundation is present", function () {
  this.marketingPackage = readMarketingPackage();
});

Then("it should use its own development command", function () {
  assert.match(this.marketingPackage.scripts?.dev ?? "", /next dev/, "Expected a standalone Next.js development command.");
});

Then("it should be configured for static hosting", function () {
  const configPath = path.join(marketingRoot, "next.config.mjs");
  assert.ok(fs.existsSync(configPath), "Expected a Next.js configuration for the marketing site.");
  assert.match(fs.readFileSync(configPath, "utf8"), /output:\s*["']export["']/);
});

Then("it should include the Papyrus plant pictogram", function () {
  assert.ok(
    fs.existsSync(path.join(marketingRoot, "public/papyrus-plant.png")),
    "Expected the existing Papyrus plant pictogram to be included in the marketing app.",
  );
});

Then("it should identify papyrus.anth.us as its intended public home", function () {
  const metadataPath = path.join(marketingRoot, "app/layout.tsx");
  assert.ok(fs.existsSync(metadataPath), "Expected marketing metadata to be defined.");
  assert.match(fs.readFileSync(metadataPath, "utf8"), /papyrus\.anth\.us/);
});
