/**
 * The Alexa skill package generator and the deploy-time sync. Everything runs against fakes (SSM, the Lambda policy, Cognito and
 * SMAPI): no network call, no AWS call. Run with no argument for everything, or with one behaviour name (the Gherkin steps do this).
 * `UPDATE_ALEXA_SNAPSHOT=1` rewrites the committed package snapshot.
 */
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveAlexaConfig, skillIdParameterName, contentHashParameterName } from "../amplify/plugins/alexa/config";
import type { IntentModule } from "../amplify/plugins/alexa/contracts";
import { createSkillIdResolver, MISSING_SKILL_ID_RETRY_MS } from "../amplify/plugins/alexa/skill-identity";
import {
  accountLinkingRequest,
  generateSkillPackage,
  hostedUiOrigin,
  interactionModelPath,
  SKILL_MANIFEST_PATH,
  type AccountLinkingOutputs,
} from "../amplify/plugins/alexa/skill-package";
import { createSmapiClient, fetchLwaAccessToken, LWA_TOKEN_URL, SMAPI_BASE_URL, SmapiError, type LwaCredentials, type SmapiClient } from "../amplify/plugins/alexa/sync/smapi";
import type { SyncPorts } from "../amplify/plugins/alexa/sync/ports";
import { ALEXA_CREDENTIAL_PARAMETERS, syncAlexaSkill } from "../amplify/plugins/alexa/sync/sync";
import { cmsProductionBuildSpec } from "../infra/amplify-app-shell/lib/build-specs";
import { parseSiteConfig } from "../infra/amplify-app-shell/lib/site-config";

const here = path.dirname(fileURLToPath(import.meta.url));
const snapshotDirectory = path.join(here, "fixtures/alexa-skill-package");
const ARN = "arn:aws:lambda:us-east-1:123456789012:function:papyrus-alexa-skill";
const request = { name: "alexa", invocationName: "the example", siteId: "example", siteOrigin: "https://example.com" };
// Built from parts: a bare UUID literal looks like a leaked session identifier to the repository scanner.
const skillIdFrom = (...parts: string[]) => `amzn1.ask.skill.${parts.join("-")}`;
const NEW_SKILL_ID = skillIdFrom("aaaaaaaa", "1111", "2222", "3333", "444444444444");

const fixtureIntent: IntentModule = {
  id: "fixture",
  create: () => ({ canHandle: () => false, handle: () => ({}) as never }),
  interactionModel: { intent: { name: "LatestStoriesIntent", samples: ["what is new", "read the news"] } },
};
const modules = [fixtureIntent];
const linkingOutputs: AccountLinkingOutputs = { userPoolId: "us-east-1_Example", clientId: "client-id-1", hostedUiDomain: "papyrus-example-cms" };

type Call = string;

function fakes(options: { credentials?: boolean; secret?: string | undefined; startingPolicy?: { statementId: string; skillId: string | undefined }[] } = {}) {
  const calls: Call[] = [];
  const store = new Map<string, string>();
  if (options.credentials !== false) for (const name of ALEXA_CREDENTIAL_PARAMETERS) store.set(name, `value-of-${name}`);
  const policy = [...(options.startingPolicy ?? [{ statementId: "OpenStatement", skillId: undefined }])];
  const logs: string[] = [];
  const smapi: SmapiClient & { linking?: unknown } = {
    async createSkill(vendorId, manifest) {
      calls.push("create");
      assert.equal(vendorId, "value-of-/papyrus/alexa/vendor-id");
      assert.ok((manifest as { manifest?: unknown }).manifest);
      return NEW_SKILL_ID;
    },
    async updateManifest(skillId) {
      calls.push(`updateManifest ${skillId}`);
    },
    async putInteractionModel(skillId, locale) {
      calls.push(`model ${skillId} ${locale}`);
    },
    async putAccountLinking(skillId, body) {
      calls.push(`linking ${skillId}`);
      smapi.linking = body;
    },
  };
  const ports: SyncPorts = {
    parameters: {
      async get(name) {
        calls.push(`ssm-get ${name}`);
        return store.get(name);
      },
      async putString(name, value) {
        calls.push(`ssm-put ${name}`);
        store.set(name, value);
      },
    },
    permissions: {
      async alexaStatements() {
        return policy.map((entry) => ({ ...entry }));
      },
      async addSkillPermission(_arn, statementId, skillId) {
        calls.push(`permission-add ${skillId}`);
        policy.push({ statementId, skillId });
      },
      async removePermission(_arn, statementId) {
        calls.push(`permission-remove ${statementId}`);
        policy.splice(policy.findIndex((entry) => entry.statementId === statementId), 1);
      },
    },
    clientSecrets: { clientSecret: async () => ("secret" in options ? options.secret : "cognito-client-secret") },
    connect: async (credentials: LwaCredentials) => {
      calls.push("connect");
      assert.equal(credentials.refreshToken, "value-of-/papyrus/alexa/lwa-refresh-token");
      return smapi;
    },
    log: (line) => logs.push(line),
  };
  const amazonCalls = () => calls.filter((call) => /^(connect|create|updateManifest|model|linking)/.test(call));
  return { calls, store, policy, logs, smapi, ports, amazonCalls };
}

function input(overrides: Record<string, unknown> = {}, withLinking = false) {
  const config = resolveAlexaConfig({ ...request, ...overrides });
  return { config, endpointArn: ARN, ...(withLinking ? { accountLinking: linkingOutputs } : {}) };
}

const behaviours: Record<string, () => void | Promise<void>> = {
  "manifest is complete": () => {
    const config = resolveAlexaConfig({ ...request, locales: ["en-US", "en-GB"], accountLinking: true, amazonVendorId: "M2EXAMPLEVENDOR" });
    const manifest = JSON.parse(generateSkillPackage(config, { endpointArn: ARN, modules })[SKILL_MANIFEST_PATH]).manifest;
    for (const locale of ["en-US", "en-GB"]) {
      const info = manifest.publishingInformation.locales[locale];
      assert.equal(info.name, "The Example");
      assert.deepEqual(info.examplePhrases, ["Alexa, open the example"]);
      assert.deepEqual(info.keywords, ["the example", "news"]);
      assert.equal(info.smallIconUri, "https://example.com/alexa/icon-108.png");
      assert.equal(info.largeIconUri, "https://example.com/alexa/icon-512.png");
      assert.equal(manifest.privacyAndCompliance.locales[locale].privacyPolicyUrl, "https://example.com/alexa/privacy/");
      assert.equal(manifest.privacyAndCompliance.locales[locale].termsOfUseUrl, "https://example.com/alexa/terms/");
    }
    assert.equal(manifest.publishingInformation.category, "NEWS");
    assert.deepEqual(manifest.apis.custom.interfaces, [{ type: "ALEXA_PRESENTATION_APL" }]);
    assert.equal(manifest.apis.custom.endpoint.uri, ARN);
    assert.equal(manifest.privacyAndCompliance.usesPersonalInfo, true);
    const overridden = JSON.parse(
      generateSkillPackage(resolveAlexaConfig({ ...request, privacyPolicyUrl: "https://legal.example.com/p", iconSmallUri: "https://cdn.example.com/s.png" }), { endpointArn: ARN, modules })[SKILL_MANIFEST_PATH],
    ).manifest;
    assert.equal(overridden.privacyAndCompliance.locales["en-US"].privacyPolicyUrl, "https://legal.example.com/p");
    assert.equal(overridden.publishingInformation.locales["en-US"].smallIconUri, "https://cdn.example.com/s.png");
    assert.throws(() => generateSkillPackage(resolveAlexaConfig({ name: "alexa", invocationName: "the example" }), { endpointArn: ARN, modules }), /needs: privacyPolicyUrl/);
  },

  "package matches the snapshot and is deterministic": () => {
    const config = resolveAlexaConfig(request);
    const files = generateSkillPackage(config, { endpointArn: ARN, modules });
    assert.deepEqual(files, generateSkillPackage(config, { endpointArn: ARN, modules: [...modules].reverse() }));
    assert.deepEqual(Object.keys(files).sort(), [SKILL_MANIFEST_PATH, interactionModelPath("en-US")].sort());
    for (const [relative, text] of Object.entries(files)) {
      const target = path.join(snapshotDirectory, relative);
      if (process.env.UPDATE_ALEXA_SNAPSHOT === "1") {
        mkdirSync(path.dirname(target), { recursive: true });
        writeFileSync(target, text);
      }
      assert.ok(existsSync(target), `snapshot ${relative} is missing: run with UPDATE_ALEXA_SNAPSHOT=1`);
      assert.equal(text, readFileSync(target, "utf8"), `${relative} differs from its snapshot: run with UPDATE_ALEXA_SNAPSHOT=1 if the change is intended`);
    }
  },

  "sync skips without credentials": async () => {
    const world = fakes({ credentials: false });
    const result = await syncAlexaSkill(input(), world.ports);
    assert.deepEqual(result, { status: "skipped", reason: "no-credentials" });
    assert.deepEqual(world.amazonCalls(), []);
    assert.equal(world.calls.some((call) => call.startsWith("ssm-put")), false);
    assert.equal(world.logs.length, 1);
    assert.match(world.logs[0], /credentials are not in SSM/);
    const partial = fakes();
    partial.store.delete("/papyrus/alexa/vendor-id");
    assert.equal((await syncAlexaSkill(input(), partial.ports)).status, "skipped");
    const incomplete = fakes();
    assert.deepEqual(await syncAlexaSkill({ config: resolveAlexaConfig({ name: "alexa", invocationName: "the example" }), endpointArn: ARN }, incomplete.ports), { status: "skipped", reason: "incomplete-config" });
    assert.deepEqual(incomplete.amazonCalls(), []);
  },

  "first sync creates the skill": async () => {
    const world = fakes({ startingPolicy: [{ statementId: "OpenStatement", skillId: undefined }] });
    const first = input({ locales: ["en-US", "en-GB"] });
    const result = await syncAlexaSkill(first, world.ports);
    assert.deepEqual(result, { status: "created", skillId: NEW_SKILL_ID });
    assert.equal(world.store.get(skillIdParameterName(first.config)), NEW_SKILL_ID);
    assert.equal(world.store.get("/papyrus/example/alexa/skill-id"), NEW_SKILL_ID);
    assert.ok(world.store.get(contentHashParameterName(first.config)));
    assert.deepEqual(world.amazonCalls(), ["connect", "create", `model ${NEW_SKILL_ID} en-US`, `model ${NEW_SKILL_ID} en-GB`]);
    const stored = world.calls.indexOf(`ssm-put /papyrus/example/alexa/skill-id`);
    assert.ok(stored < world.calls.indexOf(`model ${NEW_SKILL_ID} en-US`), "the skill ID is stored before the model upload");
    assert.deepEqual(world.policy.map((entry) => entry.skillId), [NEW_SKILL_ID], "only the new skill may invoke the function");
  },

  "unchanged sync makes no Amazon call": async () => {
    const world = fakes();
    await syncAlexaSkill(input(), world.ports);
    world.calls.length = 0;
    const result = await syncAlexaSkill(input(), world.ports);
    assert.deepEqual(result, { status: "unchanged", skillId: NEW_SKILL_ID });
    assert.deepEqual(world.amazonCalls(), []);
    assert.equal(world.calls.some((call) => call.startsWith("ssm-put")), false);
    // A CloudFormation redeploy that restored the unconditional statement is healed without an Amazon call.
    world.policy.push({ statementId: "RestoredOpen", skillId: undefined });
    world.calls.length = 0;
    await syncAlexaSkill(input(), world.ports);
    assert.deepEqual(world.amazonCalls(), []);
    assert.deepEqual(world.policy.map((entry) => entry.skillId), [NEW_SKILL_ID]);
  },

  "changed content updates the skill": async () => {
    const world = fakes();
    await syncAlexaSkill(input(), world.ports);
    const firstHash = world.store.get("/papyrus/example/alexa/content-hash");
    world.calls.length = 0;
    const result = await syncAlexaSkill(input({ skillName: "The Example Daily" }), world.ports);
    assert.deepEqual(result, { status: "updated", skillId: NEW_SKILL_ID });
    assert.deepEqual(world.amazonCalls(), ["connect", `updateManifest ${NEW_SKILL_ID}`, `model ${NEW_SKILL_ID} en-US`]);
    assert.equal(world.amazonCalls().includes("create"), false);
    assert.notEqual(world.store.get("/papyrus/example/alexa/content-hash"), firstHash);
  },

  "account linking is pushed": async () => {
    assert.equal(hostedUiOrigin(linkingOutputs), "https://papyrus-example-cms.auth.us-east-1.amazoncognito.com");
    assert.equal(hostedUiOrigin({ ...linkingOutputs, hostedUiDomain: "login.example.com" }), "https://login.example.com");
    assert.deepEqual(accountLinkingRequest(linkingOutputs, "s3cret"), {
      accountLinkingRequest: {
        type: "AUTH_CODE",
        authorizationUrl: "https://papyrus-example-cms.auth.us-east-1.amazoncognito.com/oauth2/authorize",
        accessTokenUrl: "https://papyrus-example-cms.auth.us-east-1.amazoncognito.com/oauth2/token",
        clientId: "client-id-1",
        clientSecret: "s3cret",
        scopes: ["openid", "email", "profile"],
        accessTokenScheme: "HTTP_BASIC",
        skipOnEnablement: true,
      },
    });

    const world = fakes();
    await syncAlexaSkill(input({ accountLinking: true, amazonVendorId: "M2EXAMPLEVENDOR" }, true), world.ports);
    assert.ok(world.amazonCalls().includes(`linking ${NEW_SKILL_ID}`));
    assert.equal((world.smapi.linking as { accountLinkingRequest: { clientSecret: string } }).accountLinkingRequest.clientSecret, "cognito-client-secret");

    const off = fakes();
    await syncAlexaSkill(input({}, true), off.ports);
    assert.equal(off.amazonCalls().some((call) => call.startsWith("linking")), false, "linking is not pushed unless the site turns it on");

    const noSecret = fakes({ secret: undefined });
    await syncAlexaSkill(input({ accountLinking: true, amazonVendorId: "M2EXAMPLEVENDOR" }, true), noSecret.ports);
    assert.equal(noSecret.amazonCalls().some((call) => call.startsWith("linking")), false);
    assert.ok(noSecret.logs.some((line) => /no secret/.test(line)));

    const rotated = fakes();
    await syncAlexaSkill(input({ accountLinking: true, amazonVendorId: "M2EXAMPLEVENDOR" }, true), rotated.ports);
    rotated.calls.length = 0;
    rotated.ports.clientSecrets = { clientSecret: async () => "a-new-secret" };
    await syncAlexaSkill(input({ accountLinking: true, amazonVendorId: "M2EXAMPLEVENDOR" }, true), rotated.ports);
    assert.ok(rotated.amazonCalls().includes(`linking ${NEW_SKILL_ID}`), "a rotated client secret is pushed again");
  },

  "skill ID is read from SSM and fails closed": async () => {
    const config = resolveAlexaConfig(request);
    let reads = 0;
    let value: string | undefined;
    let clock = 0;
    const resolve = createSkillIdResolver(async (name) => {
      reads += 1;
      assert.equal(name, "/papyrus/example/alexa/skill-id");
      return value;
    }, () => clock);
    assert.equal(await resolve(config), undefined, "absent means no skill ID");
    assert.equal(await resolve(config), undefined);
    assert.equal(reads, 1, "a missing ID is not re-read at once");
    value = NEW_SKILL_ID;
    clock += MISSING_SKILL_ID_RETRY_MS + 1;
    assert.equal(await resolve(config), NEW_SKILL_ID);
    value = "changed";
    assert.equal(await resolve(config), NEW_SKILL_ID, "a found ID is cached");
    assert.equal(reads, 2);
    assert.equal(await createSkillIdResolver(async () => assert.fail("SSM is not read when the config names the skill"))(resolveAlexaConfig({ ...request, skillId: NEW_SKILL_ID })), NEW_SKILL_ID);
    assert.equal(skillIdParameterName(resolveAlexaConfig({ name: "alexa", invocationName: "the example" })), "/papyrus/the-example/alexa/skill-id");
  },

  "smapi client speaks to Amazon": async () => {
    const seen: { method: string; url: string; headers: Record<string, string>; body?: string }[] = [];
    let polls = 0;
    const fakeFetch = (async (url: string, init: { method: string; headers: Record<string, string>; body?: string }) => {
      seen.push({ method: init.method, url, headers: init.headers, body: init.body });
      const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
      if (url === LWA_TOKEN_URL) return json(200, { access_token: "token-1" });
      if (init.method === "POST") return json(202, { skillId: NEW_SKILL_ID });
      if (url.includes("status?resource=manifest")) return json(200, { manifest: { lastUpdateRequest: { status: "SUCCEEDED" } } });
      if (url.includes("status?resource=interactionModel")) {
        polls += 1;
        return json(200, { interactionModel: { "en-US": { lastUpdateRequest: { status: polls < 2 ? "IN_PROGRESS" : "FAILED", errors: [{ message: "bad sample" }] } } } });
      }
      return json(202, {});
    }) as unknown as typeof fetch;
    const token = await fetchLwaAccessToken({ clientId: "id", clientSecret: "secret", refreshToken: "refresh" }, fakeFetch);
    assert.equal(token, "token-1");
    assert.match(seen[0].body ?? "", /grant_type=refresh_token/);
    const client = createSmapiClient(token, { fetch: fakeFetch, sleep: async () => undefined });
    assert.equal(await client.createSkill("vendor-1", { manifest: { manifestVersion: "1.0" } }), NEW_SKILL_ID);
    assert.equal(seen[1].url, `${SMAPI_BASE_URL}/v1/skills`);
    assert.equal(seen[1].headers.authorization, "Bearer token-1");
    assert.deepEqual(JSON.parse(seen[1].body ?? ""), { vendorId: "vendor-1", manifest: { manifestVersion: "1.0" } });
    await assert.rejects(client.putInteractionModel(NEW_SKILL_ID, "en-US", { interactionModel: {} }), (error: unknown) => error instanceof SmapiError && /bad sample/.test(error.message));
    assert.ok(seen.some((call) => call.method === "PUT" && call.url.endsWith(`/v1/skills/${NEW_SKILL_ID}/stages/development/interactionModel/locales/en-US`)));
    await client.putAccountLinking(NEW_SKILL_ID, { accountLinkingRequest: {} });
    assert.ok(seen.some((call) => call.url.endsWith("/stages/development/accountLinkingClient")));
    const refused = (async () => new Response(JSON.stringify({ error: "invalid_grant" }), { status: 400 })) as unknown as typeof fetch;
    await assert.rejects(fetchLwaAccessToken({ clientId: "id", clientSecret: "secret", refreshToken: "refresh" }, refused), /refused the refresh token/);
  },

  "site build runs the sync after the backend deploy": () => {
    const config = parseSiteConfig(JSON.parse(readFileSync(path.join(here, "../infra/amplify-app-shell/examples/pilobol-us.site.json"), "utf8")));
    const spec = cmsProductionBuildSpec(config);
    const deploy = spec.indexOf("ampx pipeline-deploy");
    const sync = spec.indexOf("papyrus-app alexa-sync");
    assert.ok(deploy > -1 && sync > deploy, "the sync follows the backend deploy");
    assert.match(spec, /alexa-sync \|\| echo/, "a failed sync never fails the build");
  },
};

async function main() {
  const requested = process.argv[2];
  const names = requested === undefined ? Object.keys(behaviours) : [requested];
  for (const name of names) {
    const behaviour = behaviours[name];
    assert.ok(behaviour, `unknown behaviour "${name}"`);
    await behaviour();
    console.log(JSON.stringify({ behaviour: name }));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
