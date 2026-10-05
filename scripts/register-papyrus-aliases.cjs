// Test-harness equivalent of the `papyrus-site` / `papyrus-amplify-outputs`
// aliases (tsconfig `paths` for tsc/tsx, `withPapyrus()` for Next). The .cjs
// tests load lib/*.ts through a hand-rolled require hook that knows neither.
const Module = require("node:module");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const aliases = {
  "papyrus-site": path.join(root, "papyrus.config.ts"),
  "papyrus-amplify-outputs": path.join(root, "amplify_outputs.json"),
};
const original = Module._resolveFilename;
Module._resolveFilename = function resolveWithPapyrusAliases(request, ...rest) {
  return original.call(this, aliases[request] ?? request, ...rest);
};
