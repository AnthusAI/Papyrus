import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import { parsePrimingProofReport } from "../lib/priming-proof-report";

const APPROVED_REPORTS_DIRECTORY = join(__dirname, "..", "lib", "approved-priming-proofs");
const REGISTRY_PATH = join(__dirname, "..", "lib", "approved-priming-proof-reports.ts");

function registrySource(brandIds: string[]): string {
  const importLines = brandIds.map((brandId, index) => `import approvedReport${index} from "./approved-priming-proofs/${brandId}.json";`);
  const entryLines = brandIds.map((brandId, index) => `  ${JSON.stringify(brandId)}: approvedReport${index},`);
  return [
    ...importLines,
    ...(importLines.length ? [""] : []),
    "/**",
    " * Priming proof reports a publication owner approved for visitors, keyed by site brand id.",
    " * A report reaches this map only through a reviewed commit made by scripts/approve-priming-proof-report.ts.",
    " */",
    `export const APPROVED_PRIMING_PROOF_REPORTS: Record<string, unknown> = {${entryLines.length ? "\n" + entryLines.join("\n") + "\n" : ""}};`,
    "",
  ].join("\n");
}

function main() {
  const [brandId, reportPath] = process.argv.slice(2);
  if (!brandId || !reportPath) {
    throw new Error("Usage: tsx scripts/approve-priming-proof-report.ts <site brand id> <report.json>");
  }
  const report = parsePrimingProofReport(JSON.parse(readFileSync(reportPath, "utf-8")));
  mkdirSync(APPROVED_REPORTS_DIRECTORY, { recursive: true });
  writeFileSync(join(APPROVED_REPORTS_DIRECTORY, `${brandId}.json`), JSON.stringify(report, null, 2) + "\n");
  const brandIds = readdirSync(APPROVED_REPORTS_DIRECTORY)
    .filter((fileName) => fileName.endsWith(".json"))
    .map((fileName) => basename(fileName, ".json"))
    .sort();
  writeFileSync(REGISTRY_PATH, registrySource(brandIds));
  console.log(`Approved ${report.proofId} for ${brandId}; registry lists ${brandIds.join(", ")}.`);
}

main();
