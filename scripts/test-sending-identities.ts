import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";

const read = (path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
const identities = read("../infra/newsletter/sending-identities.json") as { sites: Record<string, { sendingDomain: string | null }> };

const sites = readdirSync(new URL("../infra/amplify-app-shell/examples/", import.meta.url))
  .filter((name) => name.endsWith(".site.json"))
  .map((name) => name.replace(/\.site\.json$/, ""))
  .sort();

// Every site in the repository is accounted for, and the list names no site that is not here.
assert.deepEqual(Object.keys(identities.sites).sort(), sites, "sending-identities.json lists exactly the sites under infra/amplify-app-shell/examples");

const DOMAIN = /^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
for (const [site, { sendingDomain }] of Object.entries(identities.sites)) {
  if (sendingDomain !== null) assert.match(sendingDomain, DOMAIN, `${site} sendingDomain is a domain name, never an address`);
}

// Nobody shares a domain, and the sites that still need the stack are the ones the rollout names.
const domains = Object.values(identities.sites).map((entry) => entry.sendingDomain).filter((domain) => domain !== null);
assert.equal(new Set(domains).size, domains.length, "one identity per site");
const without = Object.entries(identities.sites).filter(([, entry]) => entry.sendingDomain === null).map(([site]) => site).sort();
assert.deepEqual(without, ["anth-us", "pretext", "threat-intelligence"], "sites with no sending stack yet: deploy the stack before enabling notifications there");

console.log("sending identities ok");
