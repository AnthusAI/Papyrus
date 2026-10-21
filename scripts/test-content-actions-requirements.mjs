import assert from "node:assert/strict";
import fs from "node:fs";

const resource = fs.readFileSync("amplify/functions/content-actions/resource.ts", "utf8");
const listed = [...resource.match(/contentActionsRequirements = \[(.*?)\];/s)[1].matchAll(/"([^"]+)"/g)].map((match) => match[1]);
const pinned = fs
  .readFileSync("amplify/functions/content-actions/requirements.txt", "utf8")
  .split("\n")
  .map((line) => line.trim())
  .filter((line) => line !== "" && !line.startsWith("#"));

assert.deepEqual([...listed].sort(), [...pinned].sort(), "a site deploy bundles the content-actions requirements.txt, not a different list");
console.log(`content-actions requirements agree (${listed.length} entries)`);
