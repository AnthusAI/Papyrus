import assert from "node:assert/strict";

import path from "node:path";
import { spawnSync } from "node:child_process";

const SITE_BRAND_MODULE = JSON.stringify(path.resolve(__dirname, "../lib/site-brand.ts"));
const REGISTERED_BRAND_ID = "registry-test-brand";

function probeSiteBrandModule(environmentBrandId: string | undefined, probeSource: string) {
  const environment: NodeJS.ProcessEnv = { ...process.env };
  delete environment.NEXT_PUBLIC_PAPYRUS_SITE_BRAND;
  delete environment.PAPYRUS_SITE_BRAND;
  if (environmentBrandId !== undefined) environment.PAPYRUS_SITE_BRAND = environmentBrandId;
  return spawnSync("npx", ["tsx", "-e", probeSource], { env: environment, encoding: "utf8" });
}

async function loadSiteBrandModule() {
  delete process.env.PAPYRUS_SITE_BRAND;
  delete process.env.NEXT_PUBLIC_PAPYRUS_SITE_BRAND;
  return import("../lib/site-brand");
}

async function main() {
  const { defineSite } = await import("../lib/define-site");
  const siteBrandBeforeRegistration = await loadSiteBrandModule();
  const papyrusBrand = siteBrandBeforeRegistration.getSiteBrand("papyrus");

  const site = defineSite({ brands: [{ ...papyrusBrand, id: REGISTERED_BRAND_ID }], defaultBrand: REGISTERED_BRAND_ID });
  assert.equal(site.defaultBrand, REGISTERED_BRAND_ID);
  assert.equal(site.brands?.[0].id, REGISTERED_BRAND_ID);

  const { default: repositorySite } = await import("../papyrus.config");
  for (const brand of repositorySite.brands ?? []) {
    assert.equal(siteBrandBeforeRegistration.getSiteBrand(brand.id), brand, `${brand.id} is registered from papyrus.config.ts`);
  }
  assert.deepEqual(
    (repositorySite.brands ?? []).map((brand) => brand.id).sort(),
    ["anth-us", "pilobol-us", "threat-intelligence"],
  );
  assert.equal(repositorySite.defaultBrand, "papyrus");
  assert.equal(siteBrandBeforeRegistration.resolveSiteBrandId(), "papyrus");

  const selected = probeSiteBrandModule(
    "threat-intelligence",
    `const m = require(${SITE_BRAND_MODULE}); console.log(JSON.stringify({ id: m.SITE_BRAND.id, slot: Boolean(m.SITE_BRAND.components?.PictogramFigure), demo: Boolean(m.SITE_BRAND.demoEdition) }));`,
  );
  assert.equal(selected.status, 0, selected.stderr);
  assert.deepEqual(JSON.parse(selected.stdout.trim().split("\n").pop() ?? ""), {
    id: "threat-intelligence",
    slot: true,
    demo: true,
  });

  assert.equal(siteBrandBeforeRegistration.normalizeSiteBrandId("papyrus"), "papyrus");
  assert.equal(siteBrandBeforeRegistration.normalizeSiteBrandId(" papyrus "), "papyrus");
  assert.equal(siteBrandBeforeRegistration.normalizeSiteBrandId("PAPYRUS"), null);
  assert.equal(siteBrandBeforeRegistration.normalizeSiteBrandId("pilobolus"), null);
  assert.equal(siteBrandBeforeRegistration.normalizeSiteBrandId("anthus"), null);

  assert.throws(
    () => siteBrandBeforeRegistration.resolveSiteBrandId("no-such-brand"),
    /Unknown brand 'no-such-brand'\. Registered: .*papyrus/,
  );
  assert.throws(() => siteBrandBeforeRegistration.getSiteBrand("no-such-brand"), /Unknown brand 'no-such-brand'/);

  const unknown = probeSiteBrandModule("no-such-brand", `require(${SITE_BRAND_MODULE})`);
  assert.notEqual(unknown.status, 0);
  assert.match(unknown.stderr, /Unknown brand 'no-such-brand'\. Registered: /);

  console.log("test-site-brand-registry: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
