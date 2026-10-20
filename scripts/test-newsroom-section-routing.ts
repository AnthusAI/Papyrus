import assert from "node:assert/strict";
import { resolveNewsDeskTab } from "../lib/newsroom-section-routing";

assert.equal(resolveNewsDeskTab("desks", null), "desks", "taxonomy must open its editor, not proposals");
assert.equal(resolveNewsDeskTab(["desks"], null), "desks");
for (const section of ["concepts", "references", "search", "administration", "assignments", "messages", "topics"] as const) {
  assert.equal(resolveNewsDeskTab(section, null), section);
}
assert.equal(resolveNewsDeskTab("users", null), "administration");
assert.equal(resolveNewsDeskTab("doctrine", null), "administration");
assert.equal(resolveNewsDeskTab(null, "categories"), "topics");
assert.equal(resolveNewsDeskTab("unknown", null), "overview");
console.log("PASS taxonomy editor routing, retained CMS destinations and retired aliases");
