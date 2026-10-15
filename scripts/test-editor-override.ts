import assert from "node:assert/strict";
import { testEditorOverrideAllowed } from "../lib/test-editor-override";
assert.equal(testEditorOverrideAllowed("production", "true"), false);
assert.equal(testEditorOverrideAllowed("production", undefined), false);
assert.equal(testEditorOverrideAllowed(undefined, "true"), false);
assert.equal(testEditorOverrideAllowed("development", undefined), false);
assert.equal(testEditorOverrideAllowed("development", "true"), true);
assert.equal(testEditorOverrideAllowed("test", undefined), true);
console.log("PASS fixture identity override refused in production even if flag is set");
