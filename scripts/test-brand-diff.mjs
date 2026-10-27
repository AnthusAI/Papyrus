import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { brandDiff, normalizeImports, referenceDirFor } from "../packages/papyrus/src/brand.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const quiet = () => {};
const reference = referenceDirFor("anth-us", repo);
assert.equal(reference, path.join(repo, "publications", "anth_us"));

assert.equal(
  normalizeImports('import type { SiteBrand } from "../../lib/site-brand";'),
  'import type { SiteBrand } from "@anthusai/papyrus/lib/site-brand";',
);

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "brand-diff-"));
try {
  // A site whose copy is the reference pack with package-style imports: no drift. README and index.ts are not part of a site's pack.
  const site = path.join(tmp, "site");
  fs.cpSync(reference, path.join(site, "publication"), { recursive: true });
  for (const skipped of ["README.md", "index.ts"]) fs.rmSync(path.join(site, "publication", skipped), { force: true });
  const brandFile = path.join(site, "publication", "brand.ts");
  fs.writeFileSync(brandFile, normalizeImports(fs.readFileSync(brandFile, "utf8")));
  assert.equal(brandDiff({ root: site, id: "anth-us", checkout: repo, log: quiet }).drifted, false);

  // The stale copy that motivated this check: logo component and font missing, brand.ts without the logo.
  fs.rmSync(path.join(site, "publication", "logo.tsx"));
  fs.rmSync(path.join(site, "publication", "fonts"), { recursive: true });
  fs.writeFileSync(brandFile, fs.readFileSync(brandFile, "utf8").replace(/\n\s*components:[^\n]*/, ""));
  const lines = [];
  const result = brandDiff({ root: site, id: "anth-us", checkout: repo, log: (line) => lines.push(line) });
  assert.equal(result.drifted, true);
  assert(result.missing.includes("logo.tsx") && result.missing.includes(path.join("fonts", "Jersey25-Regular.ttf")));
  assert(result.changed.includes("brand.ts"));
  assert(lines.some((line) => line.includes("missing in site: logo.tsx")));

  // Site-only files are reported but are not drift.
  fs.cpSync(reference, path.join(site, "publication"), { recursive: true });
  fs.rmSync(path.join(site, "publication", "README.md"));
  fs.rmSync(path.join(site, "publication", "index.ts"));
  fs.writeFileSync(brandFile, normalizeImports(fs.readFileSync(brandFile, "utf8")));
  fs.writeFileSync(path.join(site, "publication", "extra.css"), "");
  const extra = brandDiff({ root: site, id: "anth-us", checkout: repo, log: quiet });
  assert.deepEqual([extra.drifted, extra.extra], [false, ["extra.css"]]);

  // The CLI exits 1 on drift and 2 on an unknown brand, so a CI step can gate on it.
  const bin = path.join(repo, "packages/papyrus/bin/papyrus-app.mjs");
  fs.rmSync(path.join(site, "publication", "logo.tsx"));
  const drifted = spawnSync(process.execPath, [bin, "brand", "diff", "anth-us", "--papyrus", repo], { cwd: site, encoding: "utf8" });
  assert.equal(drifted.status, 1);
  assert.match(drifted.stdout, /missing in site: logo\.tsx/);
  const unknown = spawnSync(process.execPath, [bin, "brand", "diff", "no-such-brand", "--papyrus", repo], { cwd: site, encoding: "utf8" });
  assert.equal(unknown.status, 2);
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
console.log("PASS papyrus-app brand diff reports a site brand pack that drifted from the reference pack");
