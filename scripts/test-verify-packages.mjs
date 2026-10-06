#!/usr/bin/env node
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const verifier = path.resolve(here, "../packages/verify-packages.mjs");
const python = process.env.PAPYRUS_PYTHON || "python3";
const version = "1.2.0-next.3";
const wheelName = "papyrus_newsroom-1.2.0.dev3-py3-none-any.whl";

const baseFiles = [
  "src/backend.js",
  "amplify/site-backend.js",
  "lib/define-site.js",
  "routes.manifest.json",
  "infra/index.js",
];

function buildFixture(root, { omit, requiresDist }) {
  const packageRoot = path.join(root, "package");
  for (const file of baseFiles.filter((f) => f !== omit)) {
    fs.mkdirSync(path.dirname(path.join(packageRoot, file)), { recursive: true });
    fs.writeFileSync(path.join(packageRoot, file), "");
  }
  fs.writeFileSync(
    path.join(packageRoot, "package.json"),
    JSON.stringify({ name: "@anthusai/papyrus", version, peerDependenciesMeta: { "aws-cdk-lib": { optional: true }, constructs: { optional: true } } }),
  );
  const dist = path.join(root, "dist");
  fs.mkdirSync(dist);
  execFileSync("tar", ["-czf", path.join(dist, `anthusai-papyrus-${version}.tgz`), "-C", root, "package"]);
  const metadataPath = path.join(root, "METADATA");
  fs.writeFileSync(metadataPath, `Metadata-Version: 2.1\nName: papyrus-newsroom\nRequires-Dist: ${requiresDist}\n`);
  execFileSync(python, [
    "-c",
    "import sys,zipfile;z=zipfile.ZipFile(sys.argv[1],'w');z.write(sys.argv[2],'papyrus_newsroom-1.2.0.dev3.dist-info/METADATA');z.close()",
    path.join(dist, wheelName),
    metadataPath,
  ]);
  return dist;
}

function expectFailure(label, options, expectedText) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "verify-fixture-"));
  try {
    const dist = buildFixture(root, options);
    const result = spawnSync("node", [verifier, version, "--dist", dist, "--skip-consumer"], { encoding: "utf8" });
    if (result.status !== 1 || !result.stderr.includes(expectedText)) {
      console.error(`FAIL: ${label}: status ${result.status}, stderr ${result.stderr}`);
      process.exit(1);
    }
    console.log(`ok: ${label}`);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

expectFailure("missing src/backend.js is rejected", { omit: "src/backend.js", requiresDist: "PyYAML>=6" }, "src/backend.js");
expectFailure("file:// requirement in wheel METADATA is rejected", { omit: null, requiresDist: "tactus @ file:///x" }, "non-registry");
