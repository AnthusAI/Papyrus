import assert from "node:assert/strict";
import { resolveNewsDeskTab } from "../lib/newsroom-section-routing";

assert.equal(resolveNewsDeskTab("desks", null, true), "desks", "taxonomy must open its editor, not proposals");
assert.equal(resolveNewsDeskTab(["desks"], null, true), "desks");
assert.equal(resolveNewsDeskTab("desks", null), "topics", "other publications retain existing routing");
for (const section of ["concepts", "references", "search", "administration", "assignments", "messages", "topics"] as const) {
  assert.equal(resolveNewsDeskTab(section, null, true), section);
  assert.equal(resolveNewsDeskTab(section, null), section);
}
assert.equal(resolveNewsDeskTab("users", null, true), "administration");
assert.equal(resolveNewsDeskTab("doctrine", null, true), "administration");
assert.equal(resolveNewsDeskTab(null, "categories", true), "topics");
assert.equal(resolveNewsDeskTab("unknown", null, true), "overview");
console.log("PASS taxonomy editor routing, retained CMS destinations and legacy aliases");
