import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const checks = [
  {
    path: "app/[year]/[month]/[day]/edition-route-page.tsx",
    forbiddenPatterns: [
      "SITE_BRAND.id ===",
      "getLayoutScenario(",
      "threatIntelligenceSeedContent",
    ],
    reason: "date route should load edition content from the shared repository only",
  },
  {
    path: "app/[year]/[month]/[day]/[articleSlug]/page.tsx",
    forbiddenPatterns: [
      "SITE_BRAND.id ===",
      "getLayoutScenario(",
      "threatIntelligenceSeedContent",
    ],
    reason: "article route should resolve items from the same shared repository as edition routes",
  },
];

const failures = [];

for (const check of checks) {
  const absolutePath = resolve(check.path);
  const source = readFileSync(absolutePath, "utf8");
  for (const pattern of check.forbiddenPatterns) {
    if (source.includes(pattern)) {
      failures.push(`${check.path}: found forbidden pattern "${pattern}" (${check.reason})`);
    }
  }
}

if (failures.length > 0) {
  console.error("Reader route content-source guardrail failed:");
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log("Reader route content-source guardrail passed.");
