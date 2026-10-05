#!/usr/bin/env node
/**
 * Verify the staged release artifacts in dist-packages/.
 *   node packages/verify-packages.mjs <semver> [--dist <dir>]
 * Exits 1 with a message on the first failed check.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..");
const args = process.argv.slice(2);
const semver = args[0];
const distFlag = args.indexOf("--dist");
const distDir = path.resolve(distFlag >= 0 ? args[distFlag + 1] : path.join(repo, "dist-packages"));
const skipConsumer = args.includes("--skip-consumer");
const python = process.env.PAPYRUS_PYTHON || "python3";

if (!semver) {
  console.error("usage: node packages/verify-packages.mjs <semver>");
  process.exit(1);
}

function fail(message) {
  console.error(`FAIL: ${message}`);
  process.exit(1);
}
function pass(message) {
  console.log(`ok: ${message}`);
}
function run(command, commandArgs, options = {}) {
  return execFileSync(command, commandArgs, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], ...options });
}
function tryRun(command, commandArgs, options = {}) {
  try {
    return { status: 0, stdout: run(command, commandArgs, options), stderr: "" };
  } catch (error) {
    return { status: error.status ?? 1, stdout: String(error.stdout ?? ""), stderr: String(error.stderr ?? "") };
  }
}
function pep440(v) {
  const m = /^(\d+\.\d+\.\d+)(?:-[0-9A-Za-z-]+\.(\d+))?$/.exec(v);
  if (!m) fail(`cannot map ${v} to PEP 440`);
  return m[2] === undefined ? m[1] : `${m[1]}.dev${m[2]}`;
}

const tarball = path.join(distDir, `anthusai-papyrus-${semver}.tgz`);
if (!fs.existsSync(tarball)) fail(`tarball missing: ${tarball}`);
pass(`tarball exists (${path.basename(tarball)})`);

const listing = run("tar", ["-tzf", tarball]).split("\n");
for (const required of [
  "package/src/backend.js",
  "package/amplify/site-backend.js",
  "package/lib/define-site.js",
  "package/routes.manifest.json",
  "package/infra/index.js",
]) {
  if (!listing.includes(required)) fail(`tarball does not contain ${required}`);
}
pass("tarball ships compiled backend entry files");

const packageJson = JSON.parse(run("tar", ["-xzOf", tarball, "package/package.json"]));
if (packageJson.version !== semver) fail(`tarball version ${packageJson.version} != ${semver}`);
for (const peer of ["aws-cdk-lib", "constructs"]) {
  if (!packageJson.peerDependenciesMeta?.[peer]?.optional) fail(`peerDependenciesMeta.${peer} is not optional`);
  if (packageJson.dependencies && peer in packageJson.dependencies) fail(`dependencies contains ${peer}`);
}
pass("tarball package.json version and optional peers");

const wheelName = `papyrus_newsroom-${pep440(semver)}-py3-none-any.whl`;
const wheel = path.join(distDir, wheelName);
if (!fs.existsSync(wheel)) fail(`wheel missing: ${wheelName}`);
const wheelListing = run(python, ["-c", "import sys,zipfile;print('\\n'.join(zipfile.ZipFile(sys.argv[1]).namelist()))", wheel]).split("\n");
const metadataName = wheelListing.find((n) => n.endsWith(".dist-info/METADATA"));
if (!metadataName) fail("wheel has no METADATA");
const metadata = run(python, ["-c", "import sys,zipfile;print(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]).decode())", wheel, metadataName]);
for (const line of metadata.split("\n").filter((l) => l.startsWith("Requires-Dist:"))) {
  if (line.includes("@ file:") || line.includes("git+")) fail(`wheel METADATA has a non-registry requirement: ${line}`);
}
pass(`wheel ${wheelName} has registry-only requirements`);

if (skipConsumer) {
  console.log("skipped: consumer simulation (--skip-consumer)");
  process.exit(0);
}

const work = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-verify-"));
try {
  const consumer = path.join(work, "consumer");
  fs.mkdirSync(consumer);
  run("npm", ["init", "-y"], { cwd: consumer });
  const install = tryRun("npm", ["install", tarball, "next@15", "react@19", "react-dom@19"], { cwd: consumer });
  if (install.status !== 0) fail(`consumer npm install failed: ${install.stderr}`);
  const listed = tryRun("npm", ["ls", "aws-cdk-lib", "constructs"], { cwd: consumer });
  if (/aws-cdk-lib@|constructs@/.test(listed.stdout)) fail(`consumer install pulled optional peers:\n${listed.stdout}`);
  pass("consumer install does not install aws-cdk-lib or constructs");

  const secondVersion = "0.0.0-smoke.2";
  const secondOut = path.join(work, "second");
  run("node", [path.join(here, "papyrus/scripts/stage.mjs"), "--version", secondVersion, "--out", secondOut], { cwd: repo });
  const secondTarball = path.join(secondOut, `anthusai-papyrus-${secondVersion}.tgz`);
  if (!fs.existsSync(secondTarball)) fail(`second tarball missing: ${secondTarball}`);
  const upgrade = tryRun("npm", ["install", secondTarball], { cwd: consumer });
  if (upgrade.status !== 0) fail(`consumer upgrade install failed: ${upgrade.stderr}`);
  const cleanInstall = tryRun("npm", ["ci", "--dry-run"], { cwd: consumer });
  if (cleanInstall.status !== 0) fail(`npm ci --dry-run failed after incremental upgrade: ${cleanInstall.stderr}`);
  pass("npm ci --dry-run succeeds after incremental tarball upgrade");

  const venv = path.join(work, "venv");
  run(python, ["-m", "venv", venv]);
  const venvPython = path.join(venv, "bin", "python");
  const pip = tryRun(venvPython, ["-m", "pip", "install", "--quiet", wheel]);
  if (pip.status !== 0) fail(`pip install of the wheel failed: ${pip.stderr}`);
  const importCheck = tryRun(venvPython, ["-c", "import papyrus_content.cli"]);
  if (importCheck.status !== 0) fail(`import papyrus_content.cli failed: ${importCheck.stderr}`);
  const cli = tryRun(path.join(venv, "bin", "papyrus"), ["content", "list", "articles"]);
  if (cli.status === 0) fail("papyrus content list articles unexpectedly succeeded");
  if (/ImportError|ModuleNotFoundError/.test(cli.stderr)) fail(`papyrus CLI raised an import error:\n${cli.stderr}`);
  const shown = tryRun(venvPython, ["-m", "pip", "show", "-f", "papyrus-newsroom"]);
  if (/^\s*publications\//m.test(shown.stdout)) fail("wheel installs a publications/ path");
  pass("wheel installs, CLI imports, no publications/ in the wheel");
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}
