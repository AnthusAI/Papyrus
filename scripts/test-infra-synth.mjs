#!/usr/bin/env node
/**
 * Synth tests for the app-shell CDK stack: stage the package, lay it out as an
 * installed dependency of a scratch infra app (aws-cdk-lib and constructs are
 * linked from infra/amplify-app-shell/node_modules, so run `npm ci` there
 * first), synthesize the two example configs and assert on the templates.
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..");
const shell = path.join(repo, "infra/amplify-app-shell");
const version = "0.0.0-inf.1";
const work = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-infra-synth-"));

function run(command, args, options = {}) {
  return execFileSync(command, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], ...options });
}

function resourcesOfType(template, type) {
  return Object.values(template.Resources).filter((resource) => resource.Type === type);
}

function buildSpecOf(resource) {
  return resource.Properties.BuildSpec;
}

try {
  if (!fs.existsSync(path.join(shell, "node_modules/aws-cdk-lib"))) {
    throw new Error("run `npm ci` in infra/amplify-app-shell first (aws-cdk-lib is linked from there)");
  }
  const out = path.join(work, "dist");
  run("node", [path.join(repo, "packages/papyrus/scripts/stage.mjs"), "--version", version, "--out", out], {
    cwd: repo,
    env: { ...process.env, PAPYRUS_TS_RESOLVE_FROM: process.env.PAPYRUS_TS_RESOLVE_FROM ?? shell },
  });
  const tarball = path.join(out, `anthusai-papyrus-${version}.tgz`);

  const infraApp = path.join(work, "infra-app");
  const installed = path.join(infraApp, "node_modules/@anthusai/papyrus");
  fs.mkdirSync(installed, { recursive: true });
  run("tar", ["-xzf", tarball, "-C", installed, "--strip-components=1"]);
  for (const dependency of ["aws-cdk-lib", "constructs"]) {
    fs.symlinkSync(path.join(shell, "node_modules", dependency), path.join(infraApp, "node_modules", dependency));
  }
  const cli = path.join(installed, "bin/papyrus-infra.mjs");

  const specsSeen = [];
  for (const [example, expectedApps, expectedBranches, expectedDomains] of [
    ["pretext.site.json", 1, 2, 2],
    ["pilobol-us.site.json", 2, 3, 3],
  ]) {
    const site = path.join(shell, "examples", example);
    const siteId = JSON.parse(fs.readFileSync(site, "utf8")).siteId;
    const cdkOut = path.join(infraApp, `cdk.out.${siteId}`);
    const printed = run("node", [cli, "synth", "--site", site, "--out", cdkOut], { cwd: infraApp });
    assert.match(printed, new RegExp(`synthesized amplify-app-shell-${siteId}`));

    const templateFile = fs.readdirSync(cdkOut).find((name) => name.endsWith(".template.json"));
    const templateText = fs.readFileSync(path.join(cdkOut, templateFile), "utf8");
    assert.equal(templateText.includes("AccessToken"), false, `${example}: template contains AccessToken`);
    assert.equal(templateText.includes("Repository"), false, `${example}: template configures a repository`);
    const template = JSON.parse(templateText);

    const apps = resourcesOfType(template, "AWS::Amplify::App");
    const branches = resourcesOfType(template, "AWS::Amplify::Branch");
    const domains = resourcesOfType(template, "AWS::Amplify::Domain");
    assert.equal(apps.length, expectedApps, `${example}: app count`);
    assert.equal(branches.length, expectedBranches, `${example}: branch count`);
    assert.equal(domains.length, expectedDomains, `${example}: domain count`);

    const stagingBranch = branches.find((branch) => branch.Properties.BranchName === "staging");
    assert.ok(stagingBranch, `${example}: staging branch exists`);
    const stagingSpec = buildSpecOf(stagingBranch);
    assert.equal(/^backend:/m.test(stagingSpec), false, `${example}: staging spec has a backend phase`);
    assert.match(stagingSpec, /ampx generate outputs/);
    specsSeen.push(stagingSpec, ...apps.map(buildSpecOf));

    const productionSpec = buildSpecOf(apps.find((app) => app.Properties.Platform === "WEB_COMPUTE"));
    assert.match(productionSpec, /^backend:/m);
    assert.match(productionSpec, /npx ampx pipeline-deploy/);

    if (expectedApps === 2) {
      const readerApp = apps.find((app) => app.Properties.Platform === "WEB");
      const readerSpec = buildSpecOf(readerApp);
      assert.match(readerSpec, /uv python install 3\.12/);
      assert.match(readerSpec, /papyrus-newsroom\[markus\]==/);
      assert.equal(/^backend:/m.test(readerSpec), false);
      assert.equal(/npm run build/.test(readerSpec), false);
      assert.match(stagingSpec, /upload-preview/);
    }

    const outputs = Object.keys(template.Outputs);
    assert.ok(outputs.includes("CmsAppId"), `${example}: CmsAppId output`);
    assert.equal(outputs.includes("ReaderAppId"), expectedApps === 2, `${example}: ReaderAppId output`);
    assert.ok(outputs.includes("StagingOrigin"));
  }

  for (const spec of specsSeen) {
    assert.match(spec, /npm ci|uv pip install/, "spec installs dependencies reproducibly");
    assert.equal(/npm install/.test(spec), false, "spec uses npm install instead of npm ci");
  }
  for (const spec of specsSeen.filter((candidate) => /npm /.test(candidate))) {
    assert.match(spec, /npm ci/);
  }

  const withoutCdk = path.join(work, "no-cdk");
  fs.mkdirSync(path.join(withoutCdk, "node_modules/@anthusai"), { recursive: true });
  fs.cpSync(installed, path.join(withoutCdk, "node_modules/@anthusai/papyrus"), { recursive: true });
  let message = "";
  try {
    run("node", [path.join(withoutCdk, "node_modules/@anthusai/papyrus/bin/papyrus-infra.mjs"), "synth", "--site", path.join(shell, "examples/pretext.site.json")], { cwd: withoutCdk });
  } catch (error) {
    message = String(error.stderr);
  }
  assert.match(message, /optional peer dependencies/, "synth without the CDK must explain the optional peers");

  const staticSpec = run("node", [cli, "print-buildspec", "--site", path.join(shell, "examples/pilobol-us.site.json"), "--app", "reader"], { cwd: infraApp });
  assert.match(staticSpec, /^version: 1/);

  console.log("infra synth tests passed");
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}
