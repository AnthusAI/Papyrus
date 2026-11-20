import assert from "node:assert/strict";
import fs from "node:fs";

// Each Python Lambda that renders pages is bundled from a requirements.txt in checkout mode and from a list in its TypeScript
// definition in package mode (a site repository). The two must name the same packages.
const bundles = [
  { name: "content-actions", resource: "amplify/functions/content-actions/resource.ts", list: "contentActionsRequirements", requirements: "amplify/functions/content-actions/requirements.txt" },
  { name: "renditions", resource: "amplify/publication/renditions-function.ts", list: "renditionsRequirements", requirements: "amplify/functions/renditions/requirements.txt" },
];

for (const bundle of bundles) {
  const source = fs.readFileSync(bundle.resource, "utf8");
  const listed = [...source.match(new RegExp(`${bundle.list} = \\[(.*?)\\];`, "s"))[1].matchAll(/"([^"]+)"/g)].map((match) => match[1]);
  const pinned = fs
    .readFileSync(bundle.requirements, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "" && !line.startsWith("#"));

  assert.deepEqual([...listed].sort(), [...pinned].sort(), `a site deploy bundles the ${bundle.name} requirements.txt, not a different list`);
  console.log(`${bundle.name} requirements agree (${listed.length} entries)`);
}
