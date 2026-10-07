import assert from "node:assert/strict";
import { middlewareShim } from "../packages/papyrus/src/sync.mjs";

const withRuntime = middlewareShim({ middleware: { matcher: '["/x"]', runtime: "nodejs" } });
assert.match(withRuntime, /export const config = \{ runtime: "nodejs", matcher: \["\/x"\] \};/);

const withoutRuntime = middlewareShim({ middleware: { matcher: '["/x"]', runtime: null } });
assert.match(withoutRuntime, /export const config = \{ matcher: \["\/x"\] \};/);
assert.doesNotMatch(withoutRuntime, /runtime/);

console.log("sync middleware shim ok");
