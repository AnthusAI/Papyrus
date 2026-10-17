import assert from "node:assert/strict";
import { ORGANIZER_NAV_GROUPS, ORGANIZER_PRIMARY_NAV } from "../lib/newsroom-organizer-nav";
import { SITE_BRAND } from "../lib/site-brand";
const all = ORGANIZER_NAV_GROUPS.flatMap(group => group.items);
assert.deepEqual(all.slice(0, 3).map(item => item.label), ["Overview", "Board", SITE_BRAND.contentItemName.plural]);
assert.equal(new Set(all.map(item => item.key)).size, all.length);
assert(all.every(item => item.description.length > 15 && item.path.startsWith("/newsroom")));
for (const key of ["desks", "topics", "concepts", "search", "policies", "sections", "procedures", "users", "references"])
  assert(all.some(item => item.key === key), key);
assert.deepEqual(ORGANIZER_PRIMARY_NAV.map(item => item.key), ["overview", "board", "references", "messages"]);
console.log("PASS complete grouped organizer navigation and concise primary destination metadata");
