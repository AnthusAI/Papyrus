import assert from "node:assert/strict";
import { ORGANIZER_NAV_GROUPS, ORGANIZER_PRIMARY_NAV } from "../lib/newsroom-organizer-nav";
import { getContentItemName } from "../lib/site-brand";
const all = ORGANIZER_NAV_GROUPS.flatMap(group => group.items);
assert.deepEqual(all.slice(0, 3).map(item => item.label), ["Overview", getContentItemName().plural, "Assignments"]);
assert(!all.some(item => item.key === "search" || item.key === "topics"), "search and topic proposals are not navigation entries");
assert.deepEqual(all.filter(item => item.path.startsWith("/newsroom/administration")).map(item => item.key).sort(), ["administration", "sections"]);
assert.equal(new Set(all.map(item => item.key)).size, all.length);
assert(all.every(item => item.description.length > 15 && item.path.startsWith("/newsroom")));
for (const key of ["desks", "concepts", "sections", "administration", "references"])
  assert(all.some(item => item.key === key), key);
assert.deepEqual(ORGANIZER_PRIMARY_NAV.map(item => item.key), ["overview", "articles", "references", "messages"]);
console.log("PASS complete grouped organizer navigation and concise primary destination metadata");
