import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { papyrusVersionToPep440 } from "../infra/amplify-app-shell/lib/build-specs";
import { isStagingEnabled, parseSiteConfig, resolveStackName, resolveStagingDomainName } from "../infra/amplify-app-shell/lib/site-config";

const here = path.dirname(fileURLToPath(import.meta.url));
const examples = path.resolve(here, "../infra/amplify-app-shell/examples");
const readExample = (name: string) => JSON.parse(fs.readFileSync(path.join(examples, name), "utf8"));

function mutated(name: string, change: (config: any) => void): unknown {
  const config = readExample(name);
  change(config);
  return config;
}

function assertRejects(raw: unknown, fieldFragment: string): void {
  assert.throws(() => parseSiteConfig(raw), (error: Error) => {
    assert.match(error.message, new RegExp(fieldFragment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    return true;
  });
}

const staticConfig = parseSiteConfig(readExample("pilobol-us.site.json"));
assert.equal(staticConfig.siteId, "pilobol-us");
assert.equal(staticConfig.reader?.domainName, "pilobol.us");

const pretextConfig = parseSiteConfig(readExample("pretext.site.json"));
assert.equal(pretextConfig.frontend, "pretext");
assert.equal(pretextConfig.reader, undefined);
assert.equal(resolveStagingDomainName(pretextConfig), "staging.example.test");

assertRejects(mutated("pilobol-us.site.json", (c) => delete c.reader), "reader");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.siteId = "Pilobol_US")), "siteId");
assertRejects(
  mutated("pilobol-us.site.json", (c) => (c.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS = "http://localhost:3001/,https://newsroom.pilobol.us/")),
  "https://staging.pilobol.us/",
);
assertRejects(
  mutated("pilobol-us.site.json", (c) => (c.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS = "https://newsroom.pilobol.us/,https://staging.pilobol.us/")),
  "http://localhost:3001/",
);
assertRejects(mutated("pilobol-us.site.json", (c) => (c.frontend = "gatsby")), "frontend");
assertRejects(mutated("pretext.site.json", (c) => (c.reader = { domainName: "example.test", buildCommand: "x", baseDirectory: "dist" })), "reader");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.papyrusVersion = "latest")), "papyrusVersion");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.githubTokenSecretName = "amplify/github-app-token")), "githubTokenSecretName");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.github.branches = ["main", "release/*"])), "wildcards");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.github.branches = ["*"])), "github.branches[0]");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.github.branches = [])), "github.branches");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.github.owner = "Anthus*")), "github.owner");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.github.owner = "AnthusAI/other")), "github.owner");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.github.owner = "Other")), "must match repository");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.github.ciCanDeployInfra = "yes")), "ciCanDeployInfra");
assertRejects(mutated("pilobol-us.site.json", (c) => (c.github.token = "x")), "github.token");
const domainFree = (c: any) => {
  delete c.hostedZoneId;
  delete c.cms.domainName;
  c.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS = "http://localhost:3001/";
};
const domainFreeConfig = parseSiteConfig(mutated("pretext.site.json", domainFree));
assert.equal(domainFreeConfig.cms.domainName, undefined);
assert.equal(domainFreeConfig.hostedZoneId, undefined);
assert.equal(resolveStagingDomainName(domainFreeConfig), undefined);
const noStagingConfig = parseSiteConfig(mutated("pretext.site.json", (c) => {
  c.cms.staging = false;
  c.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS = "http://localhost:3001/,https://newsroom.example.test/";
}));
assert.equal(isStagingEnabled(noStagingConfig), false);
assert.equal(resolveStagingDomainName(noStagingConfig), undefined);
assert.deepEqual(noStagingConfig.github?.branches, ["main"]);
parseSiteConfig(mutated("pilobol-us.site.json", (c) => {
  domainFree(c);
  delete c.reader.domainName;
  delete c.cms.stagingDomainName;
}));
assertRejects(mutated("pretext.site.json", (c) => delete c.hostedZoneId), "hostedZoneId");
assertRejects(mutated("pretext.site.json", (c) => delete c.cms.domainName), "only allowed when");
assertRejects(mutated("pretext.site.json", (c) => { domainFree(c); c.hostedZoneId = "Z0000000EXAMPLE"; }), "only allowed when");
assertRejects(mutated("pretext.site.json", (c) => (c.cms.staging = "no")), "cms.staging");
assertRejects(mutated("pretext.site.json", (c) => { c.cms.staging = false; c.cms.stagingDomainName = "s.example.test"; }), "must not be set when cms.staging is false");
assertRejects(mutated("pretext.site.json", (c) => { domainFree(c); c.cms.stagingDomainName = "s.example.test"; }), "requires cms.domainName");
assertRejects(mutated("pretext.site.json", (c) => { domainFree(c); c.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS = "https://x.example.test/"; }), "http://localhost:3001/");
assert.deepEqual(pretextConfig.github?.branches, ["main", "staging"]);
assert.equal(pretextConfig.github?.ciCanDeployInfra, true);
assert.equal(staticConfig.github?.ciCanDeployInfra, false);
assertRejects("not an object", "site");

assert.equal(resolveStackName(parseSiteConfig(mutated("pretext.site.json", () => {}))), "amplify-app-shell-pretext-example");
assert.equal(resolveStackName(parseSiteConfig(mutated("pretext.site.json", (c) => (c.stackName = "pretext-new")))), "pretext-new");
assertRejects(mutated("pretext.site.json", (c) => (c.stackName = "-bad")), "stackName");

assert.equal(papyrusVersionToPep440("1.0.0"), "1.0.0");
assert.equal(papyrusVersionToPep440("1.0.0-next.12"), "1.0.0.dev12");

console.log("infra site config tests passed");
