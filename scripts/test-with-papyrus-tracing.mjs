import assert from "node:assert/strict";
import { withPapyrus, RUNTIME_TRACED_FILES } from "../packages/papyrus/src/with-papyrus.mjs";

const defaults = withPapyrus({}).outputFileTracingIncludes;
assert.deepEqual(defaults["/**"], RUNTIME_TRACED_FILES, "default includes cover corpora and amplify outputs");
assert.ok(defaults["/**"].includes("./corpora/**/*"));

const merged = withPapyrus({
  outputFileTracingIncludes: { "/**": ["./content/**/*", "./corpora/**/*"], "/api/x": ["./x/**"] },
}).outputFileTracingIncludes;
assert.deepEqual(merged["/**"], ["./content/**/*", "./corpora/**/*", "./amplify_outputs.json"], "merged without duplicates");
assert.deepEqual(merged["/api/x"], ["./x/**"], "other routes preserved");

console.log("with-papyrus tracing tests passed");
