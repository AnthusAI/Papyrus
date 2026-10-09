import assert from "node:assert/strict";
import { withPapyrus, DEFAULT_TRANSPILE_PACKAGES } from "../packages/papyrus/src/with-papyrus.mjs";
import { packageShipsTypeScriptSourceEntries } from "../packages/typescript-source-entries.mjs";

const defaults = withPapyrus({}).transpilePackages;
assert.ok(defaults.includes("@anthusai/papyrus"), "the package itself is transpiled");
assert.ok(defaults.includes("cyclotron"), "cyclotron ships TypeScript source and is transpiled by default");
assert.deepEqual(defaults, DEFAULT_TRANSPILE_PACKAGES);

const merged = withPapyrus({ transpilePackages: ["my-ui", "cyclotron"] }).transpilePackages;
assert.ok(merged.includes("my-ui"), "the publication's own list is preserved");
assert.equal(merged.filter((name) => name === "cyclotron").length, 1, "no duplicates");
assert.equal(new Set(merged).size, merged.length, "every entry is unique");

assert.equal(packageShipsTypeScriptSourceEntries({ exports: { "./x": "./src/x.tsx" } }), true);
assert.equal(packageShipsTypeScriptSourceEntries({ exports: { ".": { types: "./index.d.ts", default: "./index.js" } } }), false);
assert.equal(packageShipsTypeScriptSourceEntries({ exports: { ".": { "@zod/source": "./src/index.ts", import: "./index.js" } } }), false, "custom source conditions are opt-in and ignored");
assert.equal(packageShipsTypeScriptSourceEntries({ main: "./index.ts" }), true);

console.log("with-papyrus transpile tests passed");
