/**
 * Guest reader reads use the identityPool authMode, and every Published* model keeps its guest read rule.
 *
 *   npx tsx scripts/test-guest-read-auth.ts
 */
import fs from "node:fs";
import path from "node:path";
import { authMode } from "../lib/graphql-content-repository";
import { runWithContentSource } from "../lib/content-source-context";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

async function main() {
  assert((await runWithContentSource("published", async () => authMode())) === "identityPool", "published reads use identityPool");
  assert((await runWithContentSource("drafts", async () => authMode())) === "userPool", "draft reads use userPool");

  const schema = fs.readFileSync(path.join(__dirname, "../amplify/data/schema.ts"), "utf8");
  const starts = [...schema.matchAll(/^  (Published\w+): modelWithoutSubscriptions\(/gm)];
  assert(starts.length >= 6, `found the Published models, got ${starts.length}`);
  starts.forEach((match, index) => {
    const end = index + 1 < starts.length ? starts[index + 1].index! : schema.indexOf("\n  }", match.index!) + 1 || schema.length;
    const block = schema.slice(match.index!, Math.min(end, match.index! + 6000));
    assert(/allow\.guest\(\)\.to\(\["read"\]\)/.test(block), `${match[1]} keeps its guest read rule`);
  });
  console.log("PASS: guest read auth");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
