// Executes infra/amplify-app-shell/features/www-redirect.feature: cms.wwwRedirect adds a www sub-domain and a 301 rule to an apex production host.
// Run by scripts/test-www-redirect.ts, which starts it inside the infrastructure package (one copy of aws-cdk-lib).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AmplifyAppShellStack } from "./amplify-app-shell";
import { parseSiteConfig } from "./site-config";

const repo = path.resolve(__dirname, "../../..");
const env = { account: "111122223333", region: "us-east-1" };
const apex = (change: (config: any) => void = () => {}) => {
  const config = JSON.parse(fs.readFileSync(path.join(repo, "infra/amplify-app-shell/examples/shipped.site.json"), "utf8"));
  delete config.cms.domainPrefix;
  delete config.cms.redirects;
  delete config.cms.stagingDomainPrefix;
  delete config.cms.stagingDomainName;
  delete config.cms.siteOrigin;
  delete config.cms.consoleOrigin;
  config.cms.staging = false;
  config.cms.domainName = "example.test";
  config.hostedZoneId = "Z0000000EXAMPLE";
  config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS = "http://localhost:3001/,https://example.test/";
  change(config);
  return config;
};
const synth = (config: unknown) => Template.fromStack(new AmplifyAppShellStack(new App(), "Shell", parseSiteConfig(config), { env })).toJSON();
const resources = (template: any, type: string) => Object.values<any>(template.Resources).filter((resource) => resource.Type === type);

test("an apex production host with cms.wwwRedirect gets the www sub-domain and a 301 rule, 404-200 last", () => {
  const template = synth(apex((c) => (c.cms.wwwRedirect = true)));
  const domains = resources(template, "AWS::Amplify::Domain");
  assert.equal(domains.length, 1);
  assert.deepEqual(domains[0].Properties.SubDomainSettings.map((s: any) => s.Prefix).sort(), ["", "www"]);
  assert.ok(domains[0].Properties.SubDomainSettings.every((s: any) => s.BranchName === "main"));
  const app = resources(template, "AWS::Amplify::App").find((a) => a.Properties.Platform === "WEB_COMPUTE");
  const rules = app.Properties.CustomRules;
  assert.ok(rules.some((r: any) => r.Source === "https://www.example.test" && r.Target === "https://example.test" && r.Status === "301"));
  assert.equal(rules[rules.length - 1].Status, "404-200");
});

test("without the flag the template has only the apex sub-domain and no www rule", () => {
  const template = synth(apex());
  const domains = resources(template, "AWS::Amplify::Domain");
  assert.deepEqual(domains[0].Properties.SubDomainSettings.map((s: any) => s.Prefix), [""]);
  const app = resources(template, "AWS::Amplify::App").find((a) => a.Properties.Platform === "WEB_COMPUTE");
  assert.ok(!app.Properties.CustomRules.some((r: any) => String(r.Source).includes("www.")));
});

test("the flag needs an apex production host and a boolean", () => {
  assert.throws(() => parseSiteConfig(apex((c) => { c.cms.wwwRedirect = "yes"; })), /cms\.wwwRedirect/);
  assert.throws(() => parseSiteConfig(apex((c) => { c.cms.wwwRedirect = true; delete c.cms.domainName; })), /cms\.wwwRedirect/);
  assert.throws(() => parseSiteConfig(apex((c) => { c.cms.wwwRedirect = true; c.cms.domainPrefix = "p"; })), /cms\.wwwRedirect/);
});
