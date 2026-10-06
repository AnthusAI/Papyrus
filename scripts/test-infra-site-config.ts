import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { papyrusVersionToPep440 } from "../infra/amplify-app-shell/lib/build-specs";
import { parseSiteConfig, resolveStagingDomainName } from "../infra/amplify-app-shell/lib/site-config";

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
assertRejects("not an object", "site");

assert.equal(papyrusVersionToPep440("1.0.0"), "1.0.0");
assert.equal(papyrusVersionToPep440("1.0.0-next.12"), "1.0.0.dev12");

console.log("infra site config tests passed");
