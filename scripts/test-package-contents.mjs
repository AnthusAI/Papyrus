import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-package-contents-"));

try {
  const stageOutput = execFileSync(
    "node",
    [path.join(repo, "packages/papyrus/scripts/stage.mjs"), "--version", "0.0.0-contents.1", "--out", outDir],
    { cwd: repo, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  const report = JSON.parse(stageOutput.slice(stageOutput.indexOf("{")));
  const tarballEntries = execFileSync("tar", ["-tzf", report.tarball], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 })
    .split("\n")
    .filter(Boolean);

  const publicationEntries = tarballEntries.filter((entry) => entry.includes("publications/"));
  assert.deepEqual(publicationEntries, [], "the tarball must contain no publications/ entries");
  assert.deepEqual(
    report.externalFilesPulledIn.filter((file) => file.startsWith("publications/")),
    [],
    "staging must not pull in publications/ files",
  );
  assert.ok(tarballEntries.includes("package/lib/empty-theme.css"), "the tarball must ship lib/empty-theme.css");
  assert.ok(!tarballEntries.includes("package/app/dev-themes.css"), "the tarball must not ship app/dev-themes.css");
  for (const shipped of [
    "package/scripts/videoml/build-browser-bundle.mjs",
    "package/scripts/videoml/build-preview-bundle.mjs",
    "package/scripts/videoml/standard-entry.tsx",
    "package/lib/video-script.ts",
  ]) {
    assert.ok(tarballEntries.includes(shipped), `the tarball must ship ${shipped}`);
  }
  const manifestEntry = tarballEntries.find((entry) => entry === "package/routes.manifest.json");
  assert.ok(manifestEntry, "the tarball must ship routes.manifest.json");
  const manifest = JSON.parse(
    execFileSync("tar", ["-xzOf", report.tarball, manifestEntry], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 }),
  );
  const robotsRoute = manifest.routes.find((route) => route.file === "app/robots.ts");
  assert.ok(robotsRoute, "the route manifest must list app/robots.ts so consumers get a /robots.txt shim");
  assert.equal(robotsRoute.hasDefault, true);
  assert.equal(robotsRoute.config.dynamic, '"force-dynamic"');
  console.log("test-package-contents: ok");
} finally {
  fs.rmSync(outDir, { recursive: true, force: true });
}
