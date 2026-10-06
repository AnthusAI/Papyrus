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
    assert.equal(/jwt/i.test(stagingSpec), false, `${example}: staging spec mentions a JWT`);
    assert.equal(/jwt/i.test(templateText), false, `${example}: template mentions a JWT`);
    assert.equal(templateText.includes("ssm:"), false, `${example}: template grants SSM access`);
    specsSeen.push(stagingSpec, ...apps.map(buildSpecOf));

    const expectedPrefix = JSON.parse(fs.readFileSync(site, "utf8")).cms.cognitoDomainPrefix;
    const cmsBranches = branches.filter((candidate) => candidate.Properties.EnvironmentVariables.some((variable) => variable.Name === "PAPYRUS_OAUTH_REDIRECT_URLS"));
    assert.ok(cmsBranches.length >= 1, `${example}: CMS branches found`);
    for (const branch of cmsBranches) {
      const variables = Object.fromEntries(branch.Properties.EnvironmentVariables.map((variable) => [variable.Name, variable.Value]));
      assert.equal(variables.PAPYRUS_COGNITO_DOMAIN_PREFIX, expectedPrefix, `${example}: ${branch.Properties.BranchName} Cognito domain prefix`);
      assert.equal("PAPYRUS_DISABLE_GOOGLE_OAUTH" in variables, false, `${example}: ${branch.Properties.BranchName} disables Google sign-in`);
    }

    const productionSpec = buildSpecOf(apps.find((app) => app.Properties.Platform === "WEB_COMPUTE"));
    assert.match(productionSpec, /^backend:/m);
    assert.match(productionSpec, /npx ampx pipeline-deploy/);

    if (expectedApps === 2) {
      const readerApp = apps.find((app) => app.Properties.Platform === "WEB");
      const readerSpec = buildSpecOf(readerApp);
      assert.match(readerSpec, /uv python install 3\.12/);
      assert.match(readerSpec, /papyrus-newsroom\[markus\]==/);
      assert.match(readerSpec, /export-published --auth guest/);
      assert.equal(/refresh-jwt/.test(readerSpec), false, `${example}: reader spec mints a JWT`);
      const readerRoleKey = Object.keys(template.Resources).find((key) => key.startsWith("ReaderServiceRole") && template.Resources[key].Type === "AWS::IAM::Role");
      const readerPolicies = Object.values(template.Resources).filter((resource) => resource.Type === "AWS::IAM::Policy" && resource.Properties.Roles.some((role) => role.Ref === readerRoleKey));
      assert.ok(readerPolicies.length > 0, `${example}: reader role policy exists`);
      assert.equal(JSON.stringify(readerPolicies).includes("ssm:"), false, `${example}: reader role keeps SSM access`);
      assert.equal(/^backend:/m.test(readerSpec), false);
      assert.equal(/npm run build/.test(readerSpec), false);
      assert.match(stagingSpec, /upload-preview/);
    }

    const github = JSON.parse(fs.readFileSync(site, "utf8")).github;
    const roles = resourcesOfType(template, "AWS::IAM::Role");
    const ciRole = roles.find((role) => role.Properties.RoleName === `${siteId}-github-ci`);
    assert.ok(ciRole, `${example}: CI role exists`);
    assert.equal(ciRole.Properties.MaxSessionDuration, 3600);
    assert.equal(ciRole.Properties.ManagedPolicyArns, undefined, `${example}: CI role has managed policies`);
    const trust = ciRole.Properties.AssumeRolePolicyDocument.Statement;
    assert.equal(trust.length, 1);
    assert.equal(trust[0].Action, "sts:AssumeRoleWithWebIdentity");
    const flattenArn = (value) => (typeof value === "string" ? value : value["Fn::Join"][1].map((part) => (typeof part === "string" ? part : "aws")).join(""));
    assert.equal(flattenArn(trust[0].Principal.Federated), "arn:aws:iam::335163751677:oidc-provider/token.actions.githubusercontent.com");
    assert.deepEqual(trust[0].Condition.StringEquals, { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" });
    const expectedSubjects = (github.branches ?? ["main", "staging"]).map((branch) => `repo:${github.owner}/${github.repo}:ref:refs/heads/${branch}`);
    assert.deepEqual(trust[0].Condition.StringLike, { "token.actions.githubusercontent.com:sub": expectedSubjects });
    for (const subject of expectedSubjects) assert.equal(/[*?]/.test(subject), false, `${example}: wildcard subject ${subject}`);
    assert.equal(Object.keys(trust[0].Condition).length, 2);

    const ciStatements = ciRole.Properties.Policies
      ? ciRole.Properties.Policies.flatMap((policy) => policy.PolicyDocument.Statement)
      : Object.values(template.Resources)
          .filter((resource) => resource.Type === "AWS::IAM::Policy" && resource.Properties.Roles.some((role) => role.Ref && template.Resources[role.Ref] === ciRole))
          .flatMap((resource) => resource.Properties.PolicyDocument.Statement);
    assert.ok(ciStatements.length >= 3, `${example}: CI policy statements`);
    const asList = (value) => (Array.isArray(value) ? value : [value]);
    for (const statement of ciStatements) {
      const actions = asList(statement.Action);
      assert.equal(actions.includes("*"), false, `${example}: CI action *`);
      assert.equal(asList(statement.Resource).includes("*") && actions.some((action) => action.endsWith(":*")), false, `${example}: CI service wildcard on Resource *`);
    }
    const cloudformationStatements = ciStatements.filter((statement) => asList(statement.Action).some((action) => action.startsWith("cloudformation:")));
    assert.equal(cloudformationStatements.length, github.ciCanDeployInfra ? 1 : 0, `${example}: cloudformation statement only when ciCanDeployInfra`);
    if (github.ciCanDeployInfra) {
      assert.match(JSON.stringify(cloudformationStatements[0].Resource), new RegExp(`stack/amplify-app-shell-${siteId}/`));
    }
    const amplifyStatement = ciStatements.find((statement) => asList(statement.Action).includes("amplify:StartJob"));
    assert.deepEqual([...asList(amplifyStatement.Action)].sort(), ["amplify:GetJob", "amplify:ListBranches", "amplify:ListJobs", "amplify:StartJob"]);
    assert.equal(JSON.stringify(template).includes("AdministratorAccess"), true, "service role keeps its documented AdministratorAccess");
    assert.equal(JSON.stringify(ciRole).includes("AdministratorAccess"), false);

    const authoringRole = roles.find((role) => role.Properties.RoleName === `${siteId}-papyrus-authoring`);
    assert.ok(authoringRole, `${example}: authoring role exists`);
    const authoringTrust = authoringRole.Properties.AssumeRolePolicyDocument.Statement;
    assert.equal(authoringTrust.length, 1);
    assert.equal(authoringTrust[0].Action, "sts:AssumeRole");
    assert.deepEqual(Object.keys(authoringTrust[0].Principal), ["AWS"]);
    assert.match(JSON.stringify(authoringTrust[0].Principal.AWS), /:root/);
    assert.equal(authoringRole.Properties.ManagedPolicyArns, undefined, `${example}: authoring role has managed policies`);
    const authoringKey = Object.keys(template.Resources).find((key) => template.Resources[key] === authoringRole);
    const authoringStatements = Object.values(template.Resources)
      .filter((resource) => resource.Type === "AWS::IAM::Policy" && resource.Properties.Roles.some((role) => role.Ref === authoringKey))
      .flatMap((resource) => resource.Properties.PolicyDocument.Statement);
    const authoringAppSync = authoringStatements.find((statement) => asList(statement.Action).includes("appsync:GraphQL"));
    assert.ok(authoringAppSync, `${example}: authoring role may sign AppSync requests`);
    const appSyncResources = JSON.stringify(authoringAppSync.Resource);
    assert.match(appSyncResources, /types\/Query\/fields\/\*/);
    assert.match(appSyncResources, /types\/Mutation\/fields\/\*/);
    assert.equal(appSyncResources.includes("Subscription"), false);
    for (const statement of authoringStatements) {
      const actions = asList(statement.Action);
      assert.equal(actions.includes("*"), false, `${example}: authoring action *`);
      assert.equal(actions.some((action) => action.endsWith(":*")), false, `${example}: authoring service wildcard`);
      assert.equal(asList(statement.Resource).includes("*"), false, `${example}: authoring Resource *`);
    }
    assert.ok(ciStatements.some((statement) => asList(statement.Action).includes("appsync:GraphQL")), `${example}: CI role may sign AppSync requests`);

    const outputs = Object.keys(template.Outputs);
    assert.ok(outputs.includes("PapyrusAuthoringRoleArn"), `${example}: PapyrusAuthoringRoleArn output`);
    assert.ok(outputs.includes("GithubCiRoleArn"), `${example}: GithubCiRoleArn output`);
    assert.ok(outputs.includes("CmsAppId"), `${example}: CmsAppId output`);
    assert.equal(outputs.includes("ReaderAppId"), expectedApps === 2, `${example}: ReaderAppId output`);
    assert.ok(outputs.includes("StagingOrigin"));
  }

  const synthVariant = (label, example, change) => {
    const config = JSON.parse(fs.readFileSync(path.join(shell, "examples", example), "utf8"));
    change(config);
    const variantSite = path.join(work, `${label}.site.json`);
    fs.writeFileSync(variantSite, JSON.stringify(config));
    const variantOut = path.join(infraApp, `cdk.out.${label}`);
    run("node", [cli, "synth", "--site", variantSite, "--out", variantOut], { cwd: infraApp });
    const text = fs.readFileSync(path.join(variantOut, fs.readdirSync(variantOut).find((name) => name.endsWith(".template.json"))), "utf8");
    assert.equal(text.includes("AccessToken"), false, `${label}: AccessToken`);
    assert.equal(text.includes("OauthToken"), false, `${label}: OauthToken`);
    assert.equal(text.includes("Repository"), false, `${label}: Repository`);
    return JSON.parse(text);
  };
  const removeDomains = (config) => {
    delete config.hostedZoneId;
    delete config.cms.domainName;
    delete config.cms.stagingDomainName;
    if (config.reader) delete config.reader.domainName;
    config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS = "http://localhost:3001/";
  };

  const noDomains = synthVariant("no-domains", "pretext.site.json", removeDomains);
  assert.equal(resourcesOfType(noDomains, "AWS::Amplify::Domain").length, 0, "no domains: no Domain resources");
  const noDomainBranches = resourcesOfType(noDomains, "AWS::Amplify::Branch");
  assert.equal(noDomainBranches.length, 2, "no domains: both branches remain");
  const noDomainRedirects = JSON.stringify(noDomainBranches.find((branch) => branch.Properties.BranchName === "main").Properties.EnvironmentVariables);
  assert.match(noDomainRedirects, /https:\/\/main\./);
  assert.match(noDomainRedirects, /amplifyapp\.com|DefaultDomain/);
  assert.match(JSON.stringify(noDomains.Outputs.CmsOrigin), /DefaultDomain/);

  const noStaging = synthVariant("no-staging", "pretext.site.json", (config) => {
    config.cms.staging = false;
    config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS = "http://localhost:3001/,https://newsroom.example.test/";
  });
  assert.deepEqual(resourcesOfType(noStaging, "AWS::Amplify::Branch").map((branch) => branch.Properties.BranchName), ["main"]);
  assert.equal(resourcesOfType(noStaging, "AWS::Amplify::Domain").length, 1, "no staging: only the production domain");
  assert.equal(Object.keys(noStaging.Outputs).includes("StagingOrigin"), false);

  const bare = synthVariant("bare", "pilobol-us.site.json", (config) => {
    removeDomains(config);
    config.cms.staging = false;
  });
  assert.equal(resourcesOfType(bare, "AWS::Amplify::Domain").length, 0);
  assert.equal(resourcesOfType(bare, "AWS::Amplify::App").length, 2);
  assert.deepEqual(resourcesOfType(bare, "AWS::Amplify::Branch").map((branch) => branch.Properties.BranchName).sort(), ["main", "main"]);
  assert.ok(Object.keys(bare.Outputs).includes("ReaderOrigin"));

  for (const spec of specsSeen) {
    assert.match(spec, /npm ci|uv pip install/, "spec installs dependencies reproducibly");
    assert.equal(/npm install/.test(spec), false, "spec uses npm install instead of npm ci");
  }
  for (const spec of specsSeen) {
    for (const line of spec.split("\n").filter((candidate) => /\bpapyrus\s+(ops\s+)?content\b/.test(candidate))) {
      assert.match(line.trim(), /^- papyrus ops content /, `content command must be invoked as 'papyrus ops content': ${line.trim()}`);
    }
  }
  for (const spec of specsSeen.filter((candidate) => /npm /.test(candidate))) {
    assert.match(spec, /npm ci/);
  }

  const accountOut = path.join(infraApp, "cdk.out.account");
  const accountPrinted = run("node", [cli, "synth", "--account-stack", "github-oidc", "--out", accountOut], { cwd: infraApp });
  assert.match(accountPrinted, /synthesized github-oidc-provider/);
  const accountTemplate = JSON.parse(fs.readFileSync(path.join(accountOut, fs.readdirSync(accountOut).find((name) => name.endsWith(".template.json"))), "utf8"));
  const providers = resourcesOfType(accountTemplate, "Custom::AWSCDKOpenIdConnectProvider");
  assert.equal(providers.length, 1, "exactly one OIDC provider");
  assert.equal(Object.values(accountTemplate.Resources).filter((resource) => /OpenIdConnect|OIDC/i.test(resource.Type) && resource.Type !== "AWS::IAM::Role" && resource.Type !== "AWS::Lambda::Function").length, 1);
  assert.equal(providers[0].Properties.Url, "https://token.actions.githubusercontent.com");
  assert.deepEqual(providers[0].Properties.ClientIDList, ["sts.amazonaws.com"]);

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

  const renamed = synthVariant("renamed-stack", "pilobol-us.site.json", (config) => {
    config.stackName = "pilobol-us-new";
    config.github.ciCanDeployInfra = true;
  });
  assert.ok(renamed.Resources, "stackName variant synthesizes");
  const renamedPrinted = run("node", [cli, "synth", "--site", path.join(work, "renamed-stack.site.json"), "--out", path.join(infraApp, "cdk.out.renamed-print")], { cwd: infraApp });
  assert.match(renamedPrinted, /synthesized pilobol-us-new/);
  assert.match(JSON.stringify(renamed), /stack\/pilobol-us-new\//);

  const staticSpec = run("node", [cli, "print-buildspec", "--site", path.join(shell, "examples/pilobol-us.site.json"), "--app", "reader"], { cwd: infraApp });
  assert.match(staticSpec, /^version: 1/);
  assert.match(staticSpec, /^\s*- papyrus ops content export-published /m);
  assert.equal(/papyrus content /.test(staticSpec), false, "reader spec calls the nonexistent 'papyrus content'");

  console.log("infra synth tests passed");
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}
