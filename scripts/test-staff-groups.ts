import assert from "node:assert/strict";
import { claimGroups, hasEditorRights, STAFF_GROUPS } from "../lib/staff-groups";
import { accessForGroups } from "../lib/staging-gate";
import { readerIsStaff } from "../lib/reader-subject";

const token = (groups: unknown) => `h.${Buffer.from(JSON.stringify({ "cognito:groups": groups })).toString("base64url")}.s`;

assert.deepEqual([...STAFF_GROUPS], ["editor", "admin"]);

// An admin without the editor group has every editor right; the other groups do not.
assert.equal(hasEditorRights(["admin"]), true);
assert.equal(hasEditorRights(["editor"]), true);
assert.equal(hasEditorRights(["admin", "Google_1234"]), true, "the owner: admin plus the federated Google group");
assert.equal(hasEditorRights(["Admin"]), true, "case does not matter");
assert.equal(hasEditorRights(["curator", "reader"]), false);
assert.equal(hasEditorRights([]), false);
assert.equal(hasEditorRights(null), false);
assert.equal(hasEditorRights(undefined), false);

// Every way the claim reaches a Lambda.
assert.deepEqual(claimGroups(["admin", "Google_1"]), ["admin", "Google_1"]);
assert.deepEqual(claimGroups("[admin Google_1]"), ["admin", "Google_1"]);
assert.deepEqual(claimGroups("[admin, Google_1]"), ["admin", "Google_1"]);
assert.deepEqual(claimGroups('["admin","Google_1"]'), ["admin", "Google_1"]);
assert.deepEqual(claimGroups("admin,Google_1"), ["admin", "Google_1"]);
assert.deepEqual(claimGroups(undefined), []);
assert.equal(hasEditorRights(claimGroups("[admin Google_1]")), true);

// The places that gate on it.
assert.equal(accessForGroups(["admin"]), "ok");
assert.equal(accessForGroups(["editor"]), "ok");
assert.equal(accessForGroups(["reader"]), "forbidden");
assert.equal(accessForGroups(null), "anonymous");
assert.equal(readerIsStaff({ accessToken: token(["admin", "Google_1"]) }), true);
assert.equal(readerIsStaff({ accessToken: token(["reader"]) }), false);

console.log("PASS: admin has every editor right");
