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
  return execFileSync(command, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], ...options, env: { ...process.env, CDK_DEFAULT_ACCOUNT: "335163751677", ...options.env } });
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

  const anthUsSite = JSON.parse(fs.readFileSync(path.join(repo, "scripts/fixtures/anth-us.site.json"), "utf8"));
  anthUsSite.reader.redirects = [
    ...Array.from({ length: 402 }, (_, index) => ({ source: `/blog/post-${index}`, target: `/articles/post-${index}/` })),
  ];
  const anthUsSitePath = path.join(work, "anth-us.site.json");
  fs.writeFileSync(anthUsSitePath, JSON.stringify(anthUsSite));
  const anthUsOut = path.join(infraApp, "cdk.out.anth-us");
  run("node", [cli, "synth", "--site", anthUsSitePath, "--out", anthUsOut], { cwd: infraApp });
  const anthUsTemplate = JSON.parse(fs.readFileSync(path.join(anthUsOut, fs.readdirSync(anthUsOut).find((name) => name.endsWith(".template.json"))), "utf8"));
  assert.equal(resourcesOfType(anthUsTemplate, "AWS::Amplify::App").length, 2, "anth-us: two apps");
  const anthUsReaderApp = resourcesOfType(anthUsTemplate, "AWS::Amplify::App").find((app) => app.Properties.Platform === "WEB");
  const anthUsRules = anthUsReaderApp.Properties.CustomRules;
  assert.equal(anthUsRules.length, 403, "anth-us: 402 redirects plus the 404 catch-all");
  assert.deepEqual(anthUsRules[0], { Source: "/blog/post-0", Target: "/articles/post-0/", Status: "301" });
  assert.deepEqual(anthUsRules[402], { Source: "/<*>", Target: "/404.html", Status: "404-200" }, "anth-us: 404-200 is last");
  assert.match(anthUsReaderApp.Properties.CustomHeaders, /pattern: "\*\*\/\*\.html"/);
  assert.match(anthUsReaderApp.Properties.CustomHeaders, /value: "public, max-age=0, s-maxage=60, must-revalidate"/);
  const anthUsReaderSpec = buildSpecOf(anthUsReaderApp);
  assert.match(anthUsReaderSpec, /git submodule update --init --recursive/);
  assert.equal(/export-published/.test(anthUsReaderSpec), false, "anth-us: export skipped");
  assert.ok(anthUsReaderSpec.indexOf("papyrus-newsroom[markus]") < anthUsReaderSpec.indexOf("git submodule"), "anth-us: pre-build commands run after Python provisioning");
  const readerOnlySitePath = path.join(work, "anth-us-reader-only.site.json");
  const readerOnlySite = { ...anthUsSite };
  delete readerOnlySite.cms;
  delete readerOnlySite.github;
  delete readerOnlySite.hostedZoneId;
  readerOnlySite.reader = { ...anthUsSite.reader };
  delete readerOnlySite.reader.domainName;
  delete readerOnlySite.reader.domainPrefixes;
  fs.writeFileSync(readerOnlySitePath, JSON.stringify(readerOnlySite));
  const readerOnlyOut = path.join(infraApp, "cdk.out.anth-us-reader-only");
  run("node", [cli, "synth", "--site", readerOnlySitePath, "--out", readerOnlyOut], { cwd: infraApp });
  const readerOnlyTemplate = JSON.parse(fs.readFileSync(path.join(readerOnlyOut, fs.readdirSync(readerOnlyOut).find((name) => name.endsWith(".template.json"))), "utf8"));
  const readerOnlyApps = resourcesOfType(readerOnlyTemplate, "AWS::Amplify::App");
  assert.equal(readerOnlyApps.length, 1, "reader-only: one app");
  assert.equal(readerOnlyApps[0].Properties.Platform, "WEB", "reader-only: the app is the reader");
  assert.equal(resourcesOfType(readerOnlyTemplate, "AWS::Amplify::Branch").length, 1, "reader-only: one branch");
  assert.equal(resourcesOfType(readerOnlyTemplate, "AWS::Amplify::Domain").length, 0, "reader-only: no domain");
  assert.deepEqual(resourcesOfType(readerOnlyTemplate, "AWS::IAM::Role").map((role) => role.Properties.RoleName).filter(Boolean), ["anth-us-github-deploy"], "reader-only: the reader service role and the merge-to-main deploy role");
  assert.deepEqual(Object.keys(readerOnlyTemplate.Outputs).sort(), ["GithubDeployRoleArn", "ReaderAppId", "ReaderOrigin"], "reader-only: reader and deploy outputs only");
  assert.equal(resourcesOfType(readerOnlyTemplate, "AWS::Amplify::Branch")[0].Properties.EnableAutoBuild, false, "reader-only: Amplify auto-build is off, GitHub Actions starts the job");
  const pilobolExample = JSON.parse(fs.readFileSync(path.join(shell, "examples/pilobol-us.site.json"), "utf8"));
  function synthesizeSite(name, site) {
    const sitePath = path.join(work, `${name}.site.json`);
    fs.writeFileSync(sitePath, JSON.stringify(site));
    const outDirectory = path.join(infraApp, `cdk.out.${name}`);
    run("node", [cli, "synth", "--site", sitePath, "--out", outDirectory], { cwd: infraApp });
    return JSON.parse(fs.readFileSync(path.join(outDirectory, fs.readdirSync(outDirectory).find((file) => file.endsWith(".template.json"))), "utf8"));
  }
  const stagingBranchOf = (template) => resourcesOfType(template, "AWS::Amplify::Branch").find((branch) => branch.Properties.BranchName === "staging");
  const withReader = synthesizeSite("pilobol-with-reader", pilobolExample);
  const noReaderSite = structuredClone(pilobolExample);
  noReaderSite.cms.stagingPreview = { buildCommand: pilobolExample.reader.buildCommand, baseDirectory: pilobolExample.reader.baseDirectory };
  delete noReaderSite.reader;
  const noReader = synthesizeSite("pilobol-no-reader", noReaderSite);
  assert.equal(resourcesOfType(noReader, "AWS::Amplify::App").length, 1, "no reader: only the CMS app");
  assert.equal(resourcesOfType(noReader, "AWS::Amplify::App").some((app) => app.Properties.Platform === "WEB"), false, "no reader: no WEB reader app");
  assert.equal(resourcesOfType(noReader, "AWS::Amplify::Branch").length, 2, "no reader: production and staging branches");
  assert.equal(Object.keys(noReader.Outputs).some((name) => name.startsWith("Reader")), false, "no reader: no reader outputs");
  assert.equal(JSON.stringify(noReader).includes("ReaderServiceRole"), false, "no reader: no reader service role");
  assert.equal(buildSpecOf(stagingBranchOf(noReader)), buildSpecOf(stagingBranchOf(withReader)), "stagingPreview keeps the staging build spec byte-identical");
  const noPreviewSite = structuredClone(noReaderSite);
  delete noPreviewSite.cms.stagingPreview;
  const noPreview = synthesizeSite("pilobol-no-preview", noPreviewSite);
  assert.equal(/upload-preview/.test(buildSpecOf(stagingBranchOf(noPreview))), false, "no reader and no stagingPreview: the staging branch builds the newsroom only");

  const anthUsDomains = resourcesOfType(anthUsTemplate, "AWS::Amplify::Domain");
  assert.equal(anthUsDomains.length, 1, "anth-us: one reader domain");
  assert.deepEqual(anthUsDomains[0].Properties.SubDomainSettings.map((setting) => setting.Prefix), ["", "www"]);

  const specsSeen = [];
  for (const [example, expectedApps, expectedBranches, expectedDomains] of [
    ["pretext.site.json", 1, 2, 2],
    ["pilobol-us.site.json", 2, 3, 3],
    ["threat-intelligence.site.json", 1, 2, 1],
    ["p-apyr-us.site.json", 1, 2, 1],
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
    const ssmGrants = Object.values(template.Resources)
      .filter((resource) => resource.Type === "AWS::IAM::Policy")
      .flatMap((resource) => resource.Properties.PolicyDocument.Statement)
      .filter((statement) => JSON.stringify(statement.Action).includes("ssm:GetParameter"));
    const isPretext = JSON.parse(fs.readFileSync(site, "utf8")).frontend === "pretext";
    assert.equal(ssmGrants.length, isPretext ? 1 : 0, `${example}: SSM grants`);
    assert.equal(resourcesOfType(template, "Custom::SecureStringParameter").length, isPretext ? 1 : 0, `${example}: revalidate parameter is created by the stack`);
    assert.equal(resourcesOfType(template, "AWS::SecretsManager::Secret").length, 0, `${example}: no Secrets Manager secret`);
    if (isPretext) {
      assert.deepEqual(ssmGrants[0].Action, "ssm:GetParameter", `${example}: SSM grant is a single read`);
      assert.match(JSON.stringify(ssmGrants[0].Resource), new RegExp(`parameter/papyrus/${siteId}/revalidate-secret`), `${example}: SSM grant is the revalidate parameter`);
      const computeRoleKey = Object.keys(template.Resources).find((key) => key.startsWith("AmplifyComputeRole") && template.Resources[key].Type === "AWS::IAM::Role");
      const grantingPolicy = Object.values(template.Resources).find((resource) => resource.Type === "AWS::IAM::Policy" && JSON.stringify(resource.Properties.PolicyDocument).includes("ssm:GetParameter"));
      assert.ok(grantingPolicy.Properties.Roles.some((role) => role.Ref === computeRoleKey), `${example}: compute role holds the SSM grant`);
    }
    const productionVariables = Object.fromEntries(branches.find((branch) => branch.Properties.BranchName === "main").Properties.EnvironmentVariables.map((variable) => [variable.Name, variable.Value]));
    assert.equal(productionVariables.PAPYRUS_REVALIDATE_SECRET_PARAMETER, isPretext ? `/papyrus/${siteId}/revalidate-secret` : undefined, `${example}: revalidate parameter variable`);
    assert.equal(templateText.includes("PAPYRUS_REVALIDATE_SECRET\""), false, `${example}: template carries a secret variable`);
    specsSeen.push(stagingSpec, ...apps.map(buildSpecOf));
    assert.ok(template.Outputs.CmsComputeRoleArn, `${example}: compute role ARN is published for Prospectus registration`);
    assert.equal(templateText.includes("execute-api:Invoke"), false, `${example}: no Prospectus grant without cms.prospectusAccountsApiStageArn`);
    assert.equal(templateText.includes("PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT"), false, `${example}: no Prospectus endpoint without cms.prospectusAccountsApiStageArn`);

    const siteCms = JSON.parse(fs.readFileSync(site, "utf8")).cms;
    const expectedPrefix = siteCms.cognitoDomainPrefix;
    const cmsBranches = branches.filter((candidate) => candidate.Properties.EnvironmentVariables.some((variable) => variable.Name === "PAPYRUS_OAUTH_REDIRECT_URLS"));
    assert.ok(cmsBranches.length >= 1, `${example}: CMS branches found`);
    for (const branch of cmsBranches) {
      const variables = Object.fromEntries(branch.Properties.EnvironmentVariables.map((variable) => [variable.Name, variable.Value]));
      assert.equal(variables.PAPYRUS_COGNITO_DOMAIN_PREFIX, expectedPrefix, `${example}: ${branch.Properties.BranchName} Cognito domain prefix`);
      assert.equal(variables.PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX, siteCms.applyCognitoDomainPrefix ? "true" : undefined, `${example}: ${branch.Properties.BranchName} apply Cognito domain prefix`);
      assert.equal("PAPYRUS_DISABLE_GOOGLE_OAUTH" in variables, false, `${example}: ${branch.Properties.BranchName} disables Google sign-in`);
    }

    const productionSpec = buildSpecOf(apps.find((app) => app.Properties.Platform === "WEB_COMPUTE"));
    assert.match(productionSpec, /^backend:/m);
    assert.match(productionSpec, /npx ampx pipeline-deploy/);
    assert.equal(/cp amplify_outputs\.json \.next\/amplify_outputs\.json/.test(productionSpec), isPretext, `${example}: production ships amplify_outputs.json into the compute bundle only for a Pretext site`);
    assert.equal(/PAPYRUS_AMPLIFY_OUTPUTS/.test(productionSpec), false, `${example}: production must not set PAPYRUS_AMPLIFY_OUTPUTS (next build would read a file that does not exist yet)`);

    const outputsOrderOf = (spec) => ({
      build: spec.indexOf("npm run build"),
      copy: spec.indexOf("cp amplify_outputs.json .next/amplify_outputs.json"),
    });
    if (isPretext) {
      const order = outputsOrderOf(productionSpec);
      assert.ok(order.copy > order.build, `${example}: production copies amplify_outputs.json into .next after npm run build`);
    }

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
      assert.deepEqual(readerApp.Properties.CustomRules, [{ Source: "/<*>", Target: "/404.html", Status: "404-200" }], `${example}: reader catch-all serves a real 404 with 404.html`);
      assert.match(stagingSpec, /upload-preview/);
      assert.match(stagingSpec, /PAPYRUS_ROOT="\$PWD" papyrus ops content export-published --drafts/, `${example}: staging export finds the checkout's amplify_outputs.json`);
      assert.match(stagingSpec, /PAPYRUS_ROOT="\$PWD" papyrus ops content upload-preview/, `${example}: staging upload finds the checkout's amplify_outputs.json`);
      assert.match(stagingSpec, /cp amplify_outputs\.json \.next\/amplify_outputs\.json/, `${example}: staging ships amplify_outputs.json into the compute bundle`);
      assert.equal(/PAPYRUS_AMPLIFY_OUTPUTS/.test(stagingSpec), false, `${example}: staging must not set PAPYRUS_AMPLIFY_OUTPUTS`);
      const stagingOrder = outputsOrderOf(stagingSpec);
      assert.ok(stagingOrder.copy > stagingOrder.build, `${example}: staging copies amplify_outputs.json into .next after npm run build`);
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

    const deployRole = roles.find((role) => role.Properties.RoleName === `${siteId}-github-deploy`);
    assert.ok(deployRole, `${example}: merge-to-main deploy role exists`);
    assert.equal(deployRole.Properties.ManagedPolicyArns, undefined, `${example}: deploy role has managed policies`);
    const deployTrust = deployRole.Properties.AssumeRolePolicyDocument.Statement;
    assert.equal(deployTrust.length, 1);
    assert.equal(deployTrust[0].Action, "sts:AssumeRoleWithWebIdentity");
    assert.equal(flattenArn(deployTrust[0].Principal.Federated).endsWith(":oidc-provider/token.actions.githubusercontent.com"), true);
    assert.deepEqual(Object.keys(deployTrust[0].Condition), ["StringEquals"], `${example}: deploy trust is exact-match only`);
    assert.equal(deployTrust[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"], "sts.amazonaws.com");
    assert.deepEqual(
      asList(deployTrust[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]),
      [`repo:${github.owner}/${github.repo}:ref:refs/heads/main`],
      `${example}: deploy role trusts exactly main of the site repository`,
    );
    const deployKey = Object.keys(template.Resources).find((key) => template.Resources[key] === deployRole);
    const deployStatements = Object.values(template.Resources)
      .filter((resource) => resource.Type === "AWS::IAM::Policy" && resource.Properties.Roles.some((role) => role.Ref === deployKey))
      .flatMap((resource) => resource.Properties.PolicyDocument.Statement);
    assert.equal(deployStatements.length, 1, `${example}: deploy role has a single statement`);
    assert.deepEqual([...asList(deployStatements[0].Action)].sort(), ["amplify:GetJob", "amplify:StartJob"], `${example}: deploy role may only start and read jobs`);
    const deployResources = asList(deployStatements[0].Resource).map((resource) => JSON.stringify(resource));
    assert.equal(deployResources.length, expectedApps, `${example}: one job resource per app`);
    for (const resource of deployResources) assert.match(resource, /apps\/.*\/branches\/main\/jobs\/\*/, `${example}: deploy resource is the main branch jobs of one app`);
    for (const branch of branches.filter((candidate) => candidate.Properties.BranchName === "main")) {
      assert.equal(branch.Properties.EnableAutoBuild, false, `${example}: Amplify auto-build is off on main (GitHub Actions starts the job)`);
    }
    assert.ok(Object.keys(template.Outputs).includes("GithubDeployRoleArn"), `${example}: GithubDeployRoleArn output`);

    const outputs = Object.keys(template.Outputs);
    assert.ok(outputs.includes("PapyrusAuthoringRoleArn"), `${example}: PapyrusAuthoringRoleArn output`);
    assert.ok(outputs.includes("GithubCiRoleArn"), `${example}: GithubCiRoleArn output`);
    assert.ok(outputs.includes("CmsAppId"), `${example}: CmsAppId output`);
    assert.equal(outputs.includes("ReaderAppId"), expectedApps === 2, `${example}: ReaderAppId output`);
    assert.ok(outputs.includes("StagingOrigin"));
  }

  for (const workflowPath of [".github/workflows/amplify-deploy.yml", "infra/amplify-app-shell/examples/deploy-on-merge.workflow.yml"]) {
    const workflow = fs.readFileSync(path.join(repo, workflowPath), "utf8");
    assert.equal(/secrets\.|aws-access-key-id|aws-secret-access-key|AWS_ACCESS_KEY_ID/i.test(workflow), false, `${workflowPath}: no stored credentials`);
    assert.equal(/\benvironment:/.test(workflow), false, `${workflowPath}: no GitHub environments (the role trusts the branch subject only)`);
    assert.match(workflow, /id-token: write/, `${workflowPath}: OIDC token permission`);
  }
  const reusableDeploy = fs.readFileSync(path.join(repo, ".github/workflows/amplify-deploy.yml"), "utf8");
  assert.match(reusableDeploy, /workflow_call:/);
  assert.match(reusableDeploy, /role-to-assume: \$\{\{ inputs\.role-to-assume \}\}/);
  assert.match(reusableDeploy, /--commit-id "\$COMMIT_ID"/, "the job builds the exact commit that passed CI");
  assert.match(reusableDeploy, /get-job/, "the workflow waits for the job");
  assert.match(reusableDeploy, /LimitExceededException/, "back-to-back merges wait for the running job instead of failing");
  const callerTemplate = fs.readFileSync(path.join(shell, "examples/deploy-on-merge.workflow.yml"), "utf8");
  assert.match(callerTemplate, /needs: ci/, "deploy only after CI");
  assert.match(callerTemplate, /github\.ref == 'refs\/heads\/main'/, "deploy only from main");

  const immutableSubjectSite = structuredClone(pilobolExample);
  immutableSubjectSite.github.ownerId = 152415604;
  immutableSubjectSite.github.repoId = 1358579276;
  const immutableSubjectTemplate = synthesizeSite("pilobol-immutable-subject", immutableSubjectSite);
  const immutableRoles = resourcesOfType(immutableSubjectTemplate, "AWS::IAM::Role");
  const trustedSubjects = (roleName, key) => {
    const role = immutableRoles.find((candidate) => candidate.Properties.RoleName === roleName);
    const condition = role.Properties.AssumeRolePolicyDocument.Statement[0].Condition;
    return [condition.StringEquals?.[key] ?? condition.StringLike[key]].flat();
  };
  const subjectKey = "token.actions.githubusercontent.com:sub";
  assert.deepEqual(
    trustedSubjects("pilobol-us-github-deploy", subjectKey),
    ["repo:AnthusAI/Pilobol.us:ref:refs/heads/main", "repo:AnthusAI@152415604/Pilobol.us@1358579276:ref:refs/heads/main"],
    "immutable OIDC subject: the deploy role trusts the classic and the immutable subject of main",
  );
  assert.deepEqual(
    trustedSubjects("pilobol-us-github-ci", subjectKey),
    [
      "repo:AnthusAI/Pilobol.us:ref:refs/heads/main",
      "repo:AnthusAI@152415604/Pilobol.us@1358579276:ref:refs/heads/main",
      "repo:AnthusAI/Pilobol.us:ref:refs/heads/staging",
      "repo:AnthusAI@152415604/Pilobol.us@1358579276:ref:refs/heads/staging",
    ],
    "immutable OIDC subject: the CI role trusts both subject forms for each branch",
  );

  const privateSite = structuredClone(pilobolExample);
  privateSite.autoDeploy = false;
  const privateTemplate = synthesizeSite("pilobol-private", privateSite);
  assert.equal(resourcesOfType(privateTemplate, "AWS::IAM::Role").some((role) => role.Properties.RoleName === "pilobol-us-github-deploy"), false, "autoDeploy false: no deploy role");
  assert.equal(Object.keys(privateTemplate.Outputs).includes("GithubDeployRoleArn"), false, "autoDeploy false: no deploy output");
  assert.equal(resourcesOfType(privateTemplate, "AWS::Amplify::Branch").every((branch) => branch.Properties.EnableAutoBuild === true), true, "autoDeploy false: Amplify keeps auto-build");

  const prospectusSite = JSON.parse(fs.readFileSync(path.join(shell, "examples/p-apyr-us.site.json"), "utf8"));
  prospectusSite.cms.prospectusAccountsApiStageArn = "arn:aws:execute-api:us-east-1:712236451410:abc123defg/api";
  const prospectusSitePath = path.join(work, "p-apyr-us-prospectus.site.json");
  fs.writeFileSync(prospectusSitePath, JSON.stringify(prospectusSite));
  const prospectusOut = path.join(infraApp, "cdk.out.p-apyr-us-prospectus");
  run("node", [cli, "synth", "--site", prospectusSitePath, "--out", prospectusOut], { cwd: infraApp });
  const prospectusTemplate = JSON.parse(fs.readFileSync(path.join(prospectusOut, fs.readdirSync(prospectusOut).find((name) => name.endsWith(".template.json"))), "utf8"));
  const prospectusComputeRoleKey = Object.keys(prospectusTemplate.Resources).find((key) => key.startsWith("AmplifyComputeRole") && prospectusTemplate.Resources[key].Type === "AWS::IAM::Role");
  const prospectusInvokeStatements = Object.values(prospectusTemplate.Resources)
    .filter((resource) => resource.Type === "AWS::IAM::Policy" && resource.Properties.Roles.some((role) => role.Ref === prospectusComputeRoleKey))
    .flatMap((resource) => resource.Properties.PolicyDocument.Statement)
    .filter((statement) => statement.Action === "execute-api:Invoke");
  assert.equal(prospectusInvokeStatements.length, 1, "prospectus: the compute role holds one invoke grant");
  assert.deepEqual(prospectusInvokeStatements[0].Resource, [
    "GET/v1/identities/me", "POST/v1/identities/google/challenge", "POST/v1/identities/google/resolve", "GET/v1/accounts",
    "GET/v1/accounts/*", "POST/v1/accounts/*/authorize", "GET/v1/account-directory", "GET/v1/account-directory/*",
  ].map((route) => `arn:aws:execute-api:us-east-1:712236451410:abc123defg/api/${route}`), "prospectus: grant covers exactly the registered site routes");
  for (const branch of resourcesOfType(prospectusTemplate, "AWS::Amplify::Branch")) {
    const variables = Object.fromEntries(branch.Properties.EnvironmentVariables.map((variable) => [variable.Name, variable.Value]));
    assert.equal(variables.PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT, "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/", `prospectus: ${branch.Properties.BranchName} endpoint`);
    assert.equal(variables.PAPYRUS_PROSPECTUS_SESSION_SECRET_PARAMETER, "/papyrus/p-apyr-us/prospectus-session-sealing", `prospectus: ${branch.Properties.BranchName} session sealing parameter`);
    assert.equal("PAPYRUS_PROSPECTUS_SESSION_SECRET_ARN" in variables, false, `prospectus: ${branch.Properties.BranchName} no secret ARN variable`);
    assert.equal(variables.PAPYRUS_PROSPECTUS_SITE_PRODUCT, "papyrus-p-apyr-us", `prospectus: ${branch.Properties.BranchName} site product`);
  }
  assert.equal(resourcesOfType(prospectusTemplate, "AWS::SecretsManager::Secret").length, 0, "prospectus: no Secrets Manager secret");
  const generatedParameters = resourcesOfType(prospectusTemplate, "Custom::SecureStringParameter");
  assert.deepEqual(generatedParameters.map((parameter) => parameter.Properties.ParameterName).sort(), ["/papyrus/p-apyr-us/prospectus-session-sealing", "/papyrus/p-apyr-us/revalidate-secret"], "prospectus: generated parameters are the sealing and revalidate secrets");
  const sealingParameters = generatedParameters.filter((parameter) => parameter.Properties.ParameterName.endsWith("prospectus-session-sealing"));
  assert.equal(sealingParameters[0].Properties.ParameterName, "/papyrus/p-apyr-us/prospectus-session-sealing");
  assert.equal(sealingParameters[0].DeletionPolicy, "Retain", "prospectus: the sealing parameter survives stack deletion");
  const sealingSecretReads = Object.values(prospectusTemplate.Resources)
    .filter((resource) => resource.Type === "AWS::IAM::Policy" && resource.Properties.Roles.some((role) => role.Ref === prospectusComputeRoleKey))
    .flatMap((resource) => resource.Properties.PolicyDocument.Statement)
    .filter((statement) => statement.Sid === "ReadProspectusSessionSealingSecret");
  assert.equal(sealingSecretReads.length, 1, "prospectus: the compute role reads the sealing parameter");
  assert.equal(sealingSecretReads[0].Action, "ssm:GetParameter", "prospectus: read only, no list or decrypt grants");
  assert.equal(
    /^\[?"?\{"Fn::Join":\["",\["arn:",\{"Ref":"AWS::Partition"\},":ssm:us-east-1:\d{12}:parameter\/papyrus\/p-apyr-us\/prospectus-session-sealing"\]\]\}"?\]?$/.test(JSON.stringify(sealingSecretReads[0].Resource)),
    true,
    "prospectus: sealing parameter read is scoped to that parameter's ARN",
  );
  assert.equal(JSON.stringify(prospectusTemplate).includes("secretsmanager:GetSecretValue"), false, "prospectus: nothing reads Secrets Manager");

  const synthVariant = (label, example, change, { repositoryConnected = false } = {}) => {
    const config = JSON.parse(fs.readFileSync(path.join(shell, "examples", example), "utf8"));
    change(config);
    const variantSite = path.join(work, `${label}.site.json`);
    fs.writeFileSync(variantSite, JSON.stringify(config));
    const variantOut = path.join(infraApp, `cdk.out.${label}`);
    run("node", [cli, "synth", "--site", variantSite, "--out", variantOut], { cwd: infraApp });
    const text = fs.readFileSync(path.join(variantOut, fs.readdirSync(variantOut).find((name) => name.endsWith(".template.json"))), "utf8");
    assert.equal(text.includes("AccessToken"), repositoryConnected, `${label}: AccessToken`);
    assert.equal(text.includes("OauthToken"), false, `${label}: OauthToken`);
    assert.equal(text.includes("Repository"), repositoryConnected, `${label}: Repository`);
    return JSON.parse(text);
  };
  const removeDomains = (config) => {
    delete config.hostedZoneId;
    delete config.cms.domainName;
    delete config.cms.stagingDomainName;
    if (config.reader) {
      delete config.reader.domainName;
    }
    config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS = "http://localhost:3001/";
  };

  const sharedRoot = synthVariant("shared-root", "threat-intelligence.site.json", () => {});
  const sharedRootDomains = resourcesOfType(sharedRoot, "AWS::Amplify::Domain");
  assert.equal(sharedRootDomains.length, 1, "shared root: one association for the root domain");
  assert.equal(sharedRootDomains[0].Properties.DomainName, "anth.us");
  assert.deepEqual(sharedRootDomains[0].Properties.SubDomainSettings, [
    { BranchName: "main", Prefix: "threat-intelligence" },
    { BranchName: "staging", Prefix: "threat-intelligence-staging" },
  ]);
  assert.match(JSON.stringify(sharedRoot.Outputs.CmsOrigin), /https:\/\/threat-intelligence\.anth\.us\//);
  assert.match(JSON.stringify(sharedRoot.Outputs.StagingOrigin), /https:\/\/threat-intelligence-staging\.anth\.us\//);
  assert.equal(/(^|[^-a-z0-9])staging\.anth\.us/.test(JSON.stringify(sharedRoot)), false, "shared root: derived staging.anth.us must not appear");

  const apexRedirect = synthVariant("apex-redirect", "p-apyr-us.site.json", () => {});
  const apexRedirectDomains = resourcesOfType(apexRedirect, "AWS::Amplify::Domain");
  assert.equal(apexRedirectDomains.length, 1, "apex redirect: one association for the root domain");
  assert.equal(apexRedirectDomains[0].Properties.DomainName, "apyr.us");
  assert.deepEqual(apexRedirectDomains[0].Properties.SubDomainSettings, [
    { BranchName: "main", Prefix: "p" },
    { BranchName: "main", Prefix: "" },
    { BranchName: "staging", Prefix: "p-staging" },
  ]);
  assert.deepEqual(resourcesOfType(apexRedirect, "AWS::Amplify::App")[0].Properties.CustomRules, [
    { Source: "https://apyr.us", Target: "https://p.apyr.us", Status: "301" },
    { Source: "/<*>", Target: "/index.html", Status: "404-200" },
  ], "apex redirect rule comes before the 404-200 catch-all");
  assert.equal(/"AWS::Route53::RecordSet"/.test(JSON.stringify(apexRedirect)), false, "apex redirect: the template creates no Route 53 records (MX untouched)");
  assert.match(JSON.stringify(apexRedirect.Outputs.CmsOrigin), /https:\/\/p\.apyr\.us\//);
  assert.match(JSON.stringify(apexRedirect.Outputs.StagingOrigin), /https:\/\/p-staging\.apyr\.us\//);

  const withoutRedirects = resourcesOfType(synthVariant("no-redirects", "p-apyr-us.site.json", (config) => { delete config.cms.redirects; }), "AWS::Amplify::App")[0];
  assert.deepEqual(withoutRedirects.Properties.CustomRules, [{ Source: "/<*>", Target: "/index.html", Status: "404-200" }], "no redirects: only the catch-all");

  const singleHostDomains = resourcesOfType(synthVariant("single-host", "pretext.site.json", () => {}), "AWS::Amplify::Domain");
  assert.deepEqual(singleHostDomains.map((domain) => [domain.Properties.DomainName, domain.Properties.SubDomainSettings]).sort(), [
    ["newsroom.example.test", [{ BranchName: "main", Prefix: "" }]],
    ["staging.example.test", [{ BranchName: "staging", Prefix: "" }]],
  ], "single host sites keep one association per host with an empty prefix");

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

  const readerDomainSettings = (template) => resourcesOfType(template, "AWS::Amplify::Domain")
    .find((domain) => domain.Properties.DomainName === "pilobol.us").Properties.SubDomainSettings;
  const apexOnly = synthVariant("reader-apex-only", "pilobol-us.site.json", () => {});
  assert.deepEqual(readerDomainSettings(apexOnly), [{ BranchName: "main", Prefix: "" }], "reader domain: apex only");

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
      assert.match(line.trim(), /^- (PAPYRUS_ROOT="\$PWD" )?papyrus ops content /, `content command must be invoked as 'papyrus ops content': ${line.trim()}`);
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

  const connectedRepositoryArn = "arn:aws:secretsmanager:us-east-1:712236451410:secret:github-amplify-token-AbCdEf";
  const connected = synthVariant("connected-repository", "pilobol-us.site.json", (config) => {
    config.repositoryAccessTokenSecretArn = connectedRepositoryArn;
  }, { repositoryConnected: true });
  const connectedApps = resourcesOfType(connected, "AWS::Amplify::App");
  assert.equal(connectedApps.length, 2, "connected repository: both apps present");
  for (const app of connectedApps) {
    assert.equal(app.Properties.Repository, "https://github.com/AnthusAI/Pilobol.us", "connected repository: app points at the site repository");
    assert.equal(app.Properties.AccessToken, `{{resolve:secretsmanager:${connectedRepositoryArn}:SecretString}}`, "connected repository: token is a dynamic reference");
  }
  assert.equal(JSON.stringify(connected).includes("ghp_"), false, "connected repository: no literal token in the template");

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

  const deployingSite = JSON.parse(fs.readFileSync(path.join(shell, "examples/pilobol-us.site.json"), "utf8"));
  const productionSpecWithoutDeploy = run("node", [cli, "print-buildspec", "--site", path.join(shell, "examples/pilobol-us.site.json"), "--app", "cms-production"], { cwd: infraApp });
  assert.equal(productionSpecWithoutDeploy.includes("papyrus-infra deploy"), false, "deployment from the build is opt in");
  deployingSite.cms.deployStackInBuild = true;
  const deployingSitePath = path.join(work, "deploying.site.json");
  fs.writeFileSync(deployingSitePath, JSON.stringify(deployingSite));
  const productionSpecWithDeploy = run("node", [cli, "print-buildspec", "--site", deployingSitePath, "--app", "cms-production"], { cwd: infraApp });
  assert.match(productionSpecWithDeploy, /npx papyrus-infra deploy --site infra\/site.json --only-branch main/);

  const pilobolSitePath = path.join(shell, "examples/pilobol-us.site.json");
  const environmentWithoutAmplify = { ...process.env };
  delete environmentWithoutAmplify.AWS_APP_ID;
  delete environmentWithoutAmplify.AWS_BRANCH;
  const outsideAmplify = run("node", [cli, "deploy", "--site", pilobolSitePath], { cwd: infraApp, env: environmentWithoutAmplify });
  assert.match(outsideAmplify, /not running inside an Amplify build, skipping/);
  const otherBranch = run("node", [cli, "deploy", "--site", pilobolSitePath], { cwd: infraApp, env: { ...environmentWithoutAmplify, AWS_APP_ID: "dapp1", AWS_BRANCH: "staging" } });
  assert.match(otherBranch, /does not own the stack, skipping/);
  const otherApp = run("node", [cli, "deploy", "--site", pilobolSitePath, "--only-app-id", "downer"], { cwd: infraApp, env: { ...environmentWithoutAmplify, AWS_APP_ID: "dapp1", AWS_BRANCH: "main" } });
  assert.match(otherApp, /does not own the stack, skipping/);

  const fakeBinDirectory = path.join(work, "fake-bin");
  fs.mkdirSync(fakeBinDirectory);
  const recordedArguments = path.join(work, "npx-arguments.txt");
  fs.writeFileSync(path.join(fakeBinDirectory, "npx"), `#!/bin/sh\nprintf '%s\\n' "$@" > "${recordedArguments}"\n`, { mode: 0o755 });
  const deployOutputDirectory = path.join(work, "deploy-out");
  run("node", [cli, "deploy", "--site", pilobolSitePath, "--out", deployOutputDirectory, "--account", "123456789012"], {
    cwd: infraApp,
    env: { ...environmentWithoutAmplify, AWS_APP_ID: "dapp1", AWS_BRANCH: "main", PATH: `${fakeBinDirectory}${path.delimiter}${process.env.PATH}` },
  });
  const deployArguments = fs.readFileSync(recordedArguments, "utf8").split("\n");
  assert.equal(deployArguments[deployArguments.indexOf("--app") + 1], deployOutputDirectory, "the deploy passes the synthesized directory as the app, not a command string");
  assert.ok(fs.existsSync(path.join(deployOutputDirectory, "manifest.json")), "the deploy synthesizes before it runs the deploy");

  console.log("infra synth tests passed");
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}
