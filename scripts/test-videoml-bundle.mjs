import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildBrowserBundle } from "./videoml/build-browser-bundle.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixtureEntry = path.join(repo, "scripts/fixtures/video-bundle-entry.tsx");

function makeProject(configSource) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-videoml-bundle-"));
  fs.writeFileSync(path.join(directory, "papyrus.config.ts"), configSource);
  fs.copyFileSync(fixtureEntry, path.join(directory, "video-bundle-entry.tsx"));
  return directory;
}

const withVideo = makeProject(
  `export default { defaultBrand: "fixture", brands: [{ id: "fixture", video: { bundleEntry: "video-bundle-entry.tsx" } }] };\n`,
);
const withoutVideo = makeProject(`export default { defaultBrand: "plain", brands: [{ id: "plain" }] };\n`);
const unknownBrand = makeProject(`export default { defaultBrand: "other", brands: [{ id: "plain" }] };\n`);

try {
  const originalError = console.error;
  console.error = () => {};
  let result;
  try {
    result = await buildBrowserBundle(withVideo, {});
  } finally {
    console.error = originalError;
  }
  const bundlePath = path.join(withVideo, "public/videoml/browser-bundle.js");
  assert.equal(result.outfile, bundlePath);
  assert.ok(fs.statSync(bundlePath).size > 0, "browser-bundle.js must be non-empty");
  const bundleText = fs.readFileSync(bundlePath, "utf8");
  assert.ok(bundleText.includes("FixtureSlide"), "the bundle must contain the brand's registered component");
  assert.ok(bundleText.includes("renderFrame"), "the bundle must contain the standard renderFrame entry");

  await assert.rejects(
    () => buildBrowserBundle(withoutVideo, {}),
    /Brand 'plain' has no brand\.video\.bundleEntry/,
  );
  await assert.rejects(() => buildBrowserBundle(unknownBrand, {}), /Brand 'other' is not registered/);
  await assert.rejects(
    () => buildBrowserBundle(withVideo, { PAPYRUS_SITE_BRAND: "missing" }),
    /Brand 'missing' is not registered/,
  );
  console.log("test-videoml-bundle: ok");
} finally {
  for (const directory of [withVideo, withoutVideo, unknownBrand]) fs.rmSync(directory, { recursive: true, force: true });
}
