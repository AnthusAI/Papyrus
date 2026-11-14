/**
 * An agent on the signed-in CLI asks for a curation delegation, a person approves it in the Newsroom, and the agent relays the person's
 * accept, reject and star rating under it (PPY-05f412). Runs the real category-action Lambda against an in-memory data client; no cloud.
 *
 * `tsx scripts/test-curation-delegation-signed-in.ts [behaviour]` runs every behaviour, or the one named (the Gherkin steps run them one by one).
 */
import assert from "node:assert/strict";
import * as asyncHooks from "node:async_hooks";
import * as crypto from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { build } from "esbuild";
import { Kind, parse, valueFromASTUntyped } from "graphql";
import { schema } from "../amplify/data/schema";

type RecordValue = Record<string, unknown> & { id: string };
type Handler = (event: { info: { fieldName: string }; identity: unknown; arguments: Record<string, unknown> }) => Promise<Record<string, unknown>>;
const root = resolve(import.meta.dirname, "..");
const clone = <T,>(value: T): T => structuredClone(value);

const CLI_CLIENT = "cli-client-example";
const WEB_CLIENT = "web-client-example";
const EDITOR = "editor@example.test";
const referenceId = "reference-fixture-v1";

/** A Cognito ID token's claims as AppSync hands them to the Lambda. */
const idToken = (client: string, groups: string[], sub = "editor-sub-1", email = EDITOR) => ({
  sub, claims: { sub, aud: client, email, token_use: "id", "cognito:groups": groups },
});
/** The same person with an access token, which names the client as `client_id`. */
const accessToken = (client: string, groups: string[], sub = "editor-sub-1") => ({
  sub, claims: { sub, client_id: client, token_use: "access", "cognito:groups": groups },
});
const cliSession = idToken(CLI_CLIENT, ["editor"]);
const newsroomSession = idToken(WEB_CLIENT, ["editor"]);
const operatorOnAwsCredentials = { accountId: "fixture", cognitoIdentityId: "fixture:identity", userArn: "arn:aws:sts::fixture:assumed-role/fixture" };

async function makeBackend(options: { cliClientId?: string | null } = {}) {
  const rows = new Map<string, Map<string, RecordValue>>();
  const payloads = new Map<string, unknown>();
  const environment: Record<string, string> = {};
  if (options.cliClientId !== null) environment.CURATION_CLI_CLIENT_ID = options.cliClientId ?? CLI_CLIENT;
  const table = (name: string) => {
    if (!rows.has(name)) rows.set(name, new Map());
    return rows.get(name)!;
  };
  const model = (name: string) => ({
    get: async ({ id }: { id: string }) => ({ data: clone(table(name).get(id) ?? null) }),
    create: async (input: RecordValue) => {
      assert.ok(!table(name).has(input.id), `append-only create must not replace ${name} ${input.id}`);
      table(name).set(input.id, clone(input));
      return { data: clone(input) };
    },
    update: async (input: RecordValue) => {
      assert.ok(table(name).has(input.id), `update needs an existing ${name}`);
      const next = { ...table(name).get(input.id)!, ...clone(input) };
      table(name).set(input.id, next);
      return { data: clone(next) };
    },
    listCurationDelegationRecordsByGrantor: async (key: { grantorSub: string }) => ({
      data: [...table(name).values()].filter((row) => row.grantorSub === key.grantorSub).map(clone),
    }),
  });
  const client = { models: Object.fromEntries(["Reference", "Message", "SemanticRelation", "KnowledgeRawPayload", "CurationDelegationRecord", "NewsroomSection"].map((name) => [name, model(name)])) };
  const payloadKey = (kind: string, id: string, role: string, payloadKind: string) => JSON.stringify([kind, id, role, payloadKind]);
  const writePayload = async (_client: unknown, owner: { ownerKind: string; ownerId: string }, role: string, payloadKind: string, value: unknown) => {
    payloads.set(payloadKey(owner.ownerKind, owner.ownerId, role, payloadKind), clone(value));
  };
  const modules: Record<string, unknown> = {
    // setItemStars asks content-actions to refresh listings; nothing here reads the answer.
    "@aws-sdk/client-lambda": { LambdaClient: class { async send() { return {}; } }, InvokeCommand: class { constructor(readonly input: unknown) {} } },
    "node:async_hooks": asyncHooks,
    "node:crypto": crypto,
    "@aws-amplify/backend/function/runtime": { getAmplifyDataClientConfig: async () => ({ resourceConfig: {}, libraryOptions: {} }) },
    "aws-amplify": { Amplify: { configure: () => undefined } },
    "aws-amplify/data": { generateClient: () => client },
    "fixture:model-payloads": {
      putJsonModelPayload: writePayload,
      putTextModelPayload: writePayload,
      readJsonModelPayload: async (_client: unknown, kind: string, id: string, role: string, payloadKind: string) => clone(payloads.get(payloadKey(kind, id, role, payloadKind)) ?? null),
    },
  };
  const bundle = await build({
    absWorkingDir: root, entryPoints: ["amplify/functions/category-action/handler.ts"],
    bundle: true, write: false, platform: "node", format: "cjs", logLevel: "silent",
    external: ["@aws-amplify/backend/function/runtime", "aws-amplify", "aws-amplify/data", "@aws-sdk/client-lambda"],
    plugins: [{ name: "offline-payload-storage", setup(builder) {
      builder.onResolve({ filter: /\/shared\/model-payloads$/ }, () => ({ path: "fixture:model-payloads", external: true }));
    } }],
  });
  const fixtureModule = { exports: {} as { handler?: Handler } };
  runInNewContext(bundle.outputFiles[0].text, {
    module: fixtureModule, exports: fixtureModule.exports, process: { env: environment }, console,
    require: (name: string) => {
      assert.ok(Object.hasOwn(modules, name), `no unmocked cloud or network dependency: ${name}`);
      return modules[name];
    },
  });
  const handler = fixtureModule.exports.handler!;
  assert.ok(handler);
  table("Reference").set(referenceId, { id: referenceId, lineageId: "reference-fixture", versionNumber: 1, versionState: "current",
    corpusId: "corpus-fixture", title: "Synthetic source", curationStatus: "pending", feedStateKey: "corpus-fixture#unrated",
    feedArrivalAt: "2026-10-28T08:00:00.000Z" });
  const call = (fieldName: string, identity: unknown, args: Record<string, unknown> = {}) => handler({ info: { fieldName }, identity, arguments: args });
  const reference = () => table("Reference").get(referenceId)!;
  const storedDelegation = (delegationId: string) => JSON.parse(String(table("CurationDelegationRecord").get(delegationId)?.recordJson)) as Record<string, any>;
  return { call, table, reference, environment, payloads, payloadKey, storedDelegation };
}

type Backend = Awaited<ReturnType<typeof makeBackend>>;

function agentSecret() {
  const delegationId = `curation-delegation-${crypto.randomUUID()}`;
  const token = `${delegationId}~agent-held-secret-${crypto.randomUUID()}`;
  return { delegationId, token, tokenHash: crypto.createHash("sha256").update(token, "utf8").digest("hex") };
}

async function requested(backend: Backend, identity: unknown = cliSession, extra: Record<string, unknown> = {}) {
  const secret = agentSecret();
  const response = await backend.call("requestCurationDelegation", identity, { delegationId: secret.delegationId, tokenHash: secret.tokenHash, agentLabel: "Claude", hours: 2, ...extra });
  return { ...secret, userCode: String(response.userCode), response };
}

async function approved(backend: Backend) {
  const request = await requested(backend);
  await backend.call("approveCurationDelegation", newsroomSession, { userCode: request.userCode });
  return request;
}

const relay = (backend: Backend, fieldName: string, request: { delegationId: string; token: string }, extra: Record<string, unknown> = {}, identity: unknown = cliSession) =>
  backend.call(fieldName, identity, {
    referenceId, delegationId: request.delegationId, delegationToken: request.token, agentLabel: "Claude", onBehalfOf: EDITOR,
    instruction: "Ryan said to accept it.", ...extra,
  });

const behaviours: Record<string, () => Promise<void>> = {
  async the_cli_session_asks_a_person_approves_and_the_agent_relays() {
    const backend = await makeBackend();
    const request = await requested(backend);
    assert.match(request.userCode, /^[A-Z2-9]{4}-[A-Z2-9]{4}$/);
    assert.equal((await backend.call("getCurationDelegationStatus", cliSession, { delegationId: request.delegationId })).state, "pending");
    await assert.rejects(relay(backend, "recordDelegatedCuration", request, { action: "accept" }), /has not been approved by a person/);
    assert.equal(backend.reference().curationStatus, "pending", "a request that no person approved records nothing");
    const decision = await backend.call("approveCurationDelegation", newsroomSession, { userCode: request.userCode });
    assert.equal(decision.state, "approved");
    assert.equal((await backend.call("getCurationDelegationStatus", cliSession, { delegationId: request.delegationId })).state, "approved");
    const accepted = await relay(backend, "recordDelegatedCuration", request, { action: "accept", note: "Core topic." });
    assert.equal(accepted.status, "accepted");
    assert.equal(backend.reference().curationStatus, "accepted");
    const rejected = await relay(backend, "recordDelegatedCuration", request, { action: "reject", note: "Off topic for this site." });
    assert.equal(rejected.status, "rejected");
  },

  async a_cli_session_cannot_approve_its_own_request() {
    const backend = await makeBackend();
    const request = await requested(backend);
    // The same person, the same groups, the right code: only the client the token was issued to differs.
    await assert.rejects(backend.call("approveCurationDelegation", cliSession, { userCode: request.userCode }), /approved by a person in the Newsroom, not from the CLI session/);
    await assert.rejects(backend.call("approveCurationDelegation", accessToken(CLI_CLIENT, ["admin"]), { userCode: request.userCode }), /not from the CLI session/);
    await assert.rejects(backend.call("createCurationDelegation", cliSession, { agentLabel: "Claude", hours: 1 }), /not from the CLI session/, "creating an approved delegation outright is the same self-grant");
    await assert.rejects(backend.call("listCurationDelegations", cliSession), /not from the CLI session/, "the pending codes are not listed to the session that asked");
    assert.equal((await backend.call("getCurationDelegationStatus", cliSession, { delegationId: request.delegationId })).state, "pending");
    await assert.rejects(relay(backend, "recordDelegatedCuration", request, { action: "accept" }), /has not been approved/);
    assert.equal((await backend.call("approveCurationDelegation", newsroomSession, { userCode: request.userCode })).state, "approved");
  },

  async an_operator_on_aws_credentials_cannot_approve_and_still_asks_as_before() {
    const backend = await makeBackend();
    const request = await requested(backend, operatorOnAwsCredentials);
    await assert.rejects(backend.call("approveCurationDelegation", operatorOnAwsCredentials, { userCode: request.userCode }), /Only a person signed in to the Newsroom/);
    await backend.call("approveCurationDelegation", newsroomSession, { userCode: request.userCode });
    assert.equal((await relay(backend, "recordDelegatedCuration", request, { action: "accept" }, operatorOnAwsCredentials)).status, "accepted");
  },

  async a_backend_that_did_not_separate_the_cli_refuses_signed_in_requests() {
    const backend = await makeBackend({ cliClientId: null });
    const secret = agentSecret();
    const asking = { delegationId: secret.delegationId, tokenHash: secret.tokenHash, agentLabel: "Claude", hours: 2 };
    await assert.rejects(backend.call("requestCurationDelegation", cliSession, asking), /cliOnFederationClient/);
    await assert.rejects(backend.call("requestCurationDelegation", newsroomSession, asking), /cliOnFederationClient/);
    await assert.rejects(backend.call("getCurationDelegationStatus", cliSession, { delegationId: secret.delegationId }), /cliOnFederationClient/);
    assert.equal(backend.table("CurationDelegationRecord").size, 0, "nothing was stored");
    const operator = await requested(backend, operatorOnAwsCredentials);
    assert.equal((await backend.call("approveCurationDelegation", newsroomSession, { userCode: operator.userCode })).state, "approved", "the Newsroom approves as before");
    await assert.rejects(relay(backend, "recordDelegatedStars", operator, { stars: 3 }, cliSession), /cliOnFederationClient/);
  },

  async a_newsroom_session_does_not_make_requests() {
    const backend = await makeBackend();
    const secret = agentSecret();
    await assert.rejects(
      backend.call("requestCurationDelegation", newsroomSession, { delegationId: secret.delegationId, tokenHash: secret.tokenHash, agentLabel: "Claude" }),
      /Ask for a delegation from the CLI/,
    );
    const request = await approved(backend);
    await assert.rejects(relay(backend, "recordDelegatedCuration", request, { action: "accept" }, newsroomSession), /Ask for a delegation from the CLI/);
  },

  async only_editors_and_administrators_may_ask_approve_or_relay() {
    const backend = await makeBackend();
    const reader = idToken(CLI_CLIENT, ["reader"], "reader-sub");
    const noGroups = idToken(CLI_CLIENT, [], "plain-sub");
    const secret = agentSecret();
    for (const identity of [reader, noGroups]) {
      await assert.rejects(backend.call("requestCurationDelegation", identity, { delegationId: secret.delegationId, tokenHash: secret.tokenHash, agentLabel: "Claude" }), /Only an editor or administrator/);
    }
    const request = await requested(backend);
    await assert.rejects(backend.call("approveCurationDelegation", idToken(WEB_CLIENT, ["reader"], "reader-sub"), { userCode: request.userCode }), /Only an editor or administrator/);
    await assert.rejects(backend.call("denyCurationDelegation", idToken(WEB_CLIENT, [], "plain-sub"), { userCode: request.userCode }), /Only an editor or administrator/);
    await backend.call("approveCurationDelegation", idToken(WEB_CLIENT, ["admin"], "admin-sub"), { userCode: request.userCode });
    await assert.rejects(relay(backend, "recordDelegatedCuration", request, { action: "accept" }, reader), /Only an editor or administrator/);
    await assert.rejects(relay(backend, "recordDelegatedStars", request, { stars: 4 }, noGroups), /Only an editor or administrator/);
    assert.equal(backend.reference().curationStatus, "pending");
    assert.equal(backend.reference().starRating, undefined);
  },

  async the_declared_authorization_has_no_broad_signed_in_rule() {
    const document = parse(schema.transform().schema);
    const fields = new Map<string, any>();
    for (const definition of document.definitions) {
      if (definition.kind === Kind.OBJECT_TYPE_DEFINITION && (definition.name.value === "Mutation" || definition.name.value === "Query")) {
        for (const field of definition.fields ?? []) fields.set(field.name.value, field);
      }
    }
    // The rules AppSync enforces before the Lambda runs, read from the schema the backend deploys.
    const rulesOf = (name: string): Array<Record<string, unknown>> => {
      const field = fields.get(name);
      assert.ok(field, `${name} is in the schema`);
      const auth = field.directives?.find((directive: any) => directive.name.value === "auth");
      const rules = auth?.arguments?.find((argument: any) => argument.name.value === "rules");
      assert.ok(rules, `${name} declares authorization rules`);
      return clone(valueFromASTUntyped(rules.value)) as Array<Record<string, unknown>>;
    };
    const agentRoutes = ["requestCurationDelegation", "getCurationDelegationStatus", "recordDelegatedCuration", "recordDelegatedStars"];
    const personRoutes = ["approveCurationDelegation", "denyCurationDelegation", "createCurationDelegation", "revokeCurationDelegation", "listCurationDelegations"];
    const groups = { allow: "groups", groups: ["editor", "admin"] };
    for (const name of agentRoutes) {
      assert.deepEqual(rulesOf(name), [{ allow: "private", provider: "identityPool" }, groups],
        `${name}: the operator lane and the editor and admin groups, and no rule for any signed-in reader`);
    }
    for (const name of personRoutes) {
      assert.deepEqual(rulesOf(name), [groups], `${name}: the editor and admin groups only`);
    }
    // Compare against the declaration itself: the transform lowers it to directives, so also read the typed source for the group lists.
    for (const file of ["amplify/data/resource.ts", "amplify/data/schema.ts"]) {
      const source = readFileSync(resolve(root, file), "utf8");
      for (const name of [...agentRoutes, ...personRoutes]) {
        const start = source.indexOf(`  ${name}: a`);
        assert.ok(start >= 0, `${file} declares ${name}`);
        const block = source.slice(start, source.indexOf(".handler(", start));
        assert.ok(block.includes("allow.groups(categoryWriteGroups)"), `${file}: ${name} is open to the editor and admin groups`);
        assert.ok(!/allow\.authenticated\((?!"identityPool")/.test(block) && !/allow\.authenticated\(\)/.test(block), `${file}: ${name} has no signed-in-reader rule`);
        assert.ok(!/allow\.(publicApiKey|guest|owner|custom)/.test(block), `${file}: ${name} has no public rule`);
        const identityPool = block.includes('allow.authenticated("identityPool")');
        assert.equal(identityPool, agentRoutes.includes(name), `${file}: ${name} ${agentRoutes.includes(name) ? "keeps" : "never gets"} the operator lane`);
      }
    }
  },

  async deny_and_revoke_work_from_the_session_that_asked() {
    const backend = await makeBackend();
    const refused = await requested(backend);
    assert.equal((await backend.call("denyCurationDelegation", cliSession, { userCode: refused.userCode })).state, "denied");
    await assert.rejects(relay(backend, "recordDelegatedCuration", refused, { action: "accept" }), /has not been approved/);
    const withdrawn = await requested(backend);
    assert.equal((await backend.call("revokeCurationDelegation", cliSession, { delegationId: withdrawn.delegationId })).state, "revoked", "the session that asked can withdraw its pending request");
    const live = await approved(backend);
    assert.equal((await relay(backend, "recordDelegatedCuration", live, { action: "accept" })).status, "accepted");
    assert.equal((await backend.call("revokeCurationDelegation", newsroomSession, { delegationId: live.delegationId })).state, "revoked");
    await assert.rejects(relay(backend, "recordDelegatedCuration", live, { action: "reject", note: "Off topic." }), /was revoked/);
    await assert.rejects(relay(backend, "recordDelegatedStars", live, { stars: 4 }), /was revoked/);
    assert.equal(backend.reference().curationStatus, "accepted", "nothing was recorded after the revocation");
    assert.equal(backend.reference().starRating, undefined);
    const other = await approved(backend);
    await assert.rejects(
      backend.call("revokeCurationDelegation", idToken(WEB_CLIENT, ["editor"], "another-editor-sub", "another@example.test"), { delegationId: other.delegationId }),
      /Only the person who granted/,
    );
  },

  async the_hours_limit_and_the_expiry_hold() {
    const backend = await makeBackend();
    for (const hours of [0, -1, 73, 500]) {
      await assert.rejects(requested(backend, cliSession, { hours }), /between 1 and 72 hours/);
    }
    assert.equal(backend.table("CurationDelegationRecord").size, 0, "a request over the limit stores nothing");
    const request = await approved(backend);
    const stored = backend.storedDelegation(request.delegationId);
    const hoursGranted = (Date.parse(stored.expiresAt) - Date.parse(stored.approvedAt)) / 3_600_000;
    assert.equal(hoursGranted, 2, "the approved delegation lasts the hours that were asked for");
    const row = backend.table("CurationDelegationRecord").get(request.delegationId)!;
    backend.table("CurationDelegationRecord").set(request.delegationId, { ...row, recordJson: JSON.stringify({ ...stored, expiresAt: "2026-01-01T00:00:00.000Z" }) });
    await assert.rejects(relay(backend, "recordDelegatedCuration", request, { action: "accept" }), /has expired/);
    await assert.rejects(relay(backend, "recordDelegatedStars", request, { stars: 5 }), /has expired/);
    assert.equal(backend.reference().curationStatus, "pending");
  },

  async a_token_works_only_for_its_own_agent_person_and_site() {
    const backend = await makeBackend();
    const request = await approved(backend);
    await assert.rejects(relay(backend, "recordDelegatedCuration", request, { action: "accept", agentLabel: "Another agent" }), /different agent/);
    await assert.rejects(relay(backend, "recordDelegatedCuration", request, { action: "accept", onBehalfOf: "someone-else@example.test" }), /granted by editor@example.test, not someone-else@example.test/);
    await assert.rejects(relay(backend, "recordDelegatedCuration", { ...request, token: `${request.delegationId}~guessed` }, { action: "accept" }), /not recognized/);
    // Another site is another backend: it has never heard of this delegation, whatever the token.
    const anotherSite = await makeBackend();
    await assert.rejects(relay(anotherSite, "recordDelegatedCuration", request, { action: "accept" }), /not recognized/);
    await assert.rejects(relay(anotherSite, "recordDelegatedStars", request, { stars: 4 }), /not recognized/);
    assert.equal(anotherSite.reference().curationStatus, "pending");
    assert.equal(backend.reference().curationStatus, "pending");
  },

  async relayed_decisions_name_the_agent_and_the_delegation() {
    const backend = await makeBackend();
    const request = await approved(backend);
    await relay(backend, "recordDelegatedCuration", request, { action: "accept", note: "Core topic." });
    const vote = backend.reference();
    assert.equal(vote.curationActorKind, "human", "a delegated accept is the person's label for the Cyclotron");
    assert.equal(vote.curationStatusUpdatedBy, EDITOR);
    assert.deepEqual(JSON.parse(vote.curationDelegation as string), { delegationId: request.delegationId, relayedBy: "Claude", instruction: "Ryan said to accept it." });
    await relay(backend, "recordDelegatedStars", request, { stars: 4 });
    assert.equal(backend.reference().starRating, 4);
    assert.equal(backend.reference().starRatedBy, `${EDITOR} via Claude (delegation ${request.delegationId})`, "a relayed rating is never filed as the person's own");
    assert.equal(backend.reference().curationStatus, "accepted", "stars never change the vote");
    // The audit record keeps the agent, the approver and the session that asked.
    const stored = backend.storedDelegation(request.delegationId);
    assert.equal(stored.agentLabel, "Claude");
    assert.equal(stored.grantorLabel, EDITOR);
    assert.equal(stored.grantorSub, "editor-sub-1");
    assert.equal(stored.requestedBySub, "editor-sub-1");
    assert.ok(stored.approvedAt && stored.expiresAt && stored.tokenHash);
    assert.ok(!JSON.stringify(stored).includes("agent-held-secret"), "the secret half of the token is never stored");
  },

  async a_direct_vote_from_a_cli_session_is_the_signed_in_persons_with_a_via_note() {
    const backend = await makeBackend();
    await backend.call("reviewReferenceCuration", cliSession, { referenceId, action: "accept", agentLabel: "Claude" });
    assert.equal(backend.reference().curationActorKind, "human", "an agent in the editor's session votes as the editor");
    assert.equal(backend.reference().curationDelegation, null, "no delegation is needed or recorded");
    assert.match(String(backend.reference().curationStatusUpdatedBy), /via cli \(Claude\)$/, "where it came from is a plain note");
    const unreadable = { sub: "editor-sub-1", claims: { sub: "editor-sub-1", email: EDITOR, "cognito:groups": ["editor"] } };
    await backend.call("reviewReferenceCuration", unreadable, { referenceId, action: "accept" });
    assert.match(String(backend.reference().curationStatusUpdatedBy), /via signed-in$/);
    await assert.rejects(backend.call("reviewReferenceCuration", idToken(CLI_CLIENT, []), { referenceId, action: "accept" }), /Only an editor or administrator/);
    await backend.call("reviewReferenceCuration", newsroomSession, { referenceId, action: "accept" });
    assert.equal(backend.reference().curationActorKind, "human");
    const unseparated = await makeBackend({ cliClientId: null });
    await unseparated.call("reviewReferenceCuration", cliSession, { referenceId, action: "accept" });
    assert.equal(unseparated.reference().curationActorKind, "human", "without a separate CLI client nothing tells the two apart, so the vote is unchanged");
  },

  async stars_follow_the_set_reference_stars_rules() {
    const backend = await makeBackend();
    const request = await approved(backend);
    for (const stars of [0, 6, 2.5, "x"]) {
      await assert.rejects(relay(backend, "recordDelegatedStars", request, { stars }), /stars must be an integer from 1 to 5|Int cannot represent|Variable/);
    }
    assert.equal(backend.reference().starRating, undefined, "a bad rating writes nothing");
    const rated = await relay(backend, "recordDelegatedStars", request, { stars: 4 });
    // Rating a pending Reference accepts it, relayed under the same delegation; later ratings leave that status alone.
    assert.deepEqual([rated.ok, rated.stars, rated.status], [true, 4, "accepted"]);
    assert.equal(backend.reference().curationStatus, "accepted");
    assert.equal((JSON.parse(backend.reference().curationDelegation as string) as { relayedBy: string }).relayedBy, "Claude", "the acceptance is the editor's, relayed by the agent");
    assert.equal(backend.reference().starFeedKey, "corpus-fixture#stars#4");
    assert.ok(backend.reference().starRatedAt);
    await relay(backend, "recordDelegatedStars", request, { stars: 5 });
    assert.equal(backend.reference().starRating, 5, "the newest rating wins");
    assert.equal(backend.reference().starFeedKey, "corpus-fixture#stars#5");
    await relay(backend, "recordDelegatedStars", request, { stars: null });
    assert.deepEqual([backend.reference().starRating, backend.reference().starRatedAt, backend.reference().starRatedBy, backend.reference().starFeedKey], [null, null, null, null], "clearing removes who and when too");
    // A Reference with no arrival time gets one, or the star index would not hold it.
    const bare = "reference-bare-v1";
    backend.table("Reference").set(bare, { id: bare, lineageId: "reference-bare", versionNumber: 1, versionState: "current", corpusId: "corpus-fixture", curationStatus: "accepted", createdAt: "2026-10-01T00:00:00.000Z" });
    await backend.call("recordDelegatedStars", cliSession, { referenceId: bare, stars: 4, delegationId: request.delegationId, delegationToken: request.token, agentLabel: "Claude", onBehalfOf: EDITOR, instruction: "Four stars." });
    assert.equal(backend.table("Reference").get(bare)!.feedArrivalAt, "2026-10-01T00:00:00.000Z");
    assert.equal(backend.table("Reference").get(bare)!.curationStatus, "accepted", "stars leave the vote alone");
  },

  async a_delegation_forged_through_the_editor_writable_models_is_never_believed() {
    const backend = await makeBackend();
    // What an editor's session can do by itself: make a KnowledgeRawPayload row with any id (editor groups can write that model) and attach a
    // JSON file to it with createModelAttachmentUpload (an allowed owner kind and role), which is where delegations used to be read from.
    const forged = agentSecret();
    const approvedRecord = {
      delegationId: forged.delegationId, tokenHash: forged.tokenHash, grantorSub: "editor-sub-1", grantorLabel: EDITOR, agentLabel: "Claude",
      createdAt: "2026-11-04T00:00:00.000Z", expiresAt: "2099-01-01T00:00:00.000Z", revokedAt: null, approvedAt: "2026-11-04T00:00:00.000Z",
    };
    const oldPlace = (id: string) => backend.payloadKey("knowledgeRawPayload", id, "raw_payload", "curation-delegation");
    backend.table("KnowledgeRawPayload").set(forged.delegationId, { id: forged.delegationId, ownerType: "curationDelegation", ownerId: "editor-sub-1", payloadKind: "curation-delegation" });
    backend.payloads.set(oldPlace(forged.delegationId), approvedRecord);
    await assert.rejects(relay(backend, "recordDelegatedCuration", forged, { action: "accept" }), /not recognized/);
    await assert.rejects(relay(backend, "recordDelegatedStars", forged, { stars: 5 }), /not recognized/);
    await assert.rejects(backend.call("getCurationDelegationStatus", cliSession, { delegationId: forged.delegationId }), /not found/);
    // Overwriting a real pending request's old-place file changes nothing: the record is not read from there.
    const pending = await requested(backend);
    backend.table("KnowledgeRawPayload").set(pending.delegationId, { id: pending.delegationId, ownerType: "curationDelegation", ownerId: "editor-sub-1", payloadKind: "curation-delegation" });
    backend.payloads.set(oldPlace(pending.delegationId), { ...approvedRecord, delegationId: pending.delegationId, tokenHash: pending.tokenHash });
    await assert.rejects(relay(backend, "recordDelegatedCuration", pending, { action: "accept" }), /has not been approved/);
    assert.equal((await backend.call("getCurationDelegationStatus", cliSession, { delegationId: pending.delegationId })).state, "pending");
    // A row in the real table whose record disagrees with the row about its id or grantor was not written by this Lambda: it is ignored.
    const odd = agentSecret();
    backend.table("CurationDelegationRecord").set(odd.delegationId, { id: odd.delegationId, grantorSub: "someone-else", createdAt: "2026-11-04T00:00:00.000Z", recordJson: JSON.stringify({ ...approvedRecord, delegationId: odd.delegationId, tokenHash: odd.tokenHash }) });
    await assert.rejects(relay(backend, "recordDelegatedCuration", odd, { action: "accept" }), /not recognized/);
    assert.equal(backend.reference().curationStatus, "pending", "nothing was recorded");
    // The honest path still works end to end.
    const honest = await approved(backend);
    assert.equal((await relay(backend, "recordDelegatedCuration", honest, { action: "accept" })).status, "accepted");
    assert.equal(backend.table("KnowledgeRawPayload").has(honest.delegationId), false, "real delegations are not kept in the editor-writable model");
  },

  async no_session_can_write_the_delegation_records() {
    const document = parse(schema.transform().schema);
    const type = document.definitions.find((definition) => definition.kind === Kind.OBJECT_TYPE_DEFINITION && definition.name.value === "CurationDelegationRecord");
    assert.ok(type?.kind === Kind.OBJECT_TYPE_DEFINITION, "the delegation records have their own model");
    const auth = type.directives?.find((directive) => directive.name.value === "auth");
    const rules = auth?.arguments?.find((argument) => argument.name.value === "rules");
    assert.ok(rules);
    assert.deepEqual(clone(valueFromASTUntyped(rules.value)), [{ allow: "groups", operations: ["read"], groups: ["admin"] }],
      "no group, identity-pool, public or owner rule can create or update a delegation record; only the function grants write");
    for (const file of ["amplify/data/resource.ts", "amplify/data/schema.ts"]) {
      const source = readFileSync(resolve(root, file), "utf8");
      const start = source.indexOf("CurationDelegationRecord: ");
      const block = source.slice(start, source.indexOf("KnowledgeArtifact: ", start));
      assert.ok(block.includes('allow.groups([adminGroup]).to(["read"])') && !/allow\.(?!groups\(\[adminGroup\]\)\.to\(\["read"\]\))/.test(block.replace(/\/\/.*$/gm, "")), `${file}: read-only rule only`);
    }
  },

  async a_token_whose_client_cannot_be_read_can_do_nothing_with_delegations() {
    const backend = await makeBackend();
    const unreadable = { sub: "editor-sub-1", claims: { sub: "editor-sub-1", email: EDITOR, "cognito:groups": ["editor", "admin"] } };
    const blank = { sub: "editor-sub-1", claims: { sub: "editor-sub-1", aud: "  ", client_id: "", "cognito:groups": ["admin"] } };
    const request = await requested(backend);
    const secret = agentSecret();
    for (const identity of [unreadable, blank]) {
      await assert.rejects(backend.call("approveCurationDelegation", identity, { userCode: request.userCode }), /could not be read/);
      await assert.rejects(backend.call("createCurationDelegation", identity, { agentLabel: "Claude", hours: 1 }), /could not be read/);
      await assert.rejects(backend.call("listCurationDelegations", identity), /could not be read/);
      await assert.rejects(backend.call("denyCurationDelegation", identity, { userCode: request.userCode }), /could not be read/);
      await assert.rejects(backend.call("revokeCurationDelegation", identity, { delegationId: request.delegationId }), /could not be read/);
      await assert.rejects(backend.call("requestCurationDelegation", identity, { delegationId: secret.delegationId, tokenHash: secret.tokenHash, agentLabel: "Claude" }), /could not be read/);
      await assert.rejects(backend.call("getCurationDelegationStatus", identity, { delegationId: request.delegationId }), /could not be read/);
    }
    assert.equal((await backend.call("getCurationDelegationStatus", cliSession, { delegationId: request.delegationId })).state, "pending", "the request is still waiting");
  },

  async a_cli_session_rates_as_the_person_with_a_via_note() {
    const backend = await makeBackend();
    assert.equal((await backend.call("setReferenceStars", cliSession, { referenceId, stars: 5, actorLabel: EDITOR, agentLabel: "Claude" })).stars, 5);
    assert.equal(backend.reference().starRating, 5);
    assert.equal(backend.reference().starRatedBy, `${EDITOR} via cli (Claude)`);
    // This fixture has no Item model, so a Story rating gets past the session checks and stops at reading the Story: no CLI refusal.
    await assert.rejects(backend.call("setItemStars", cliSession, { itemId: "item-1", stars: 4, actorLabel: EDITOR }), (error: Error) => !/CLI session|Only an editor/.test(error.message));
    await assert.rejects(backend.call("setReferenceStars", idToken(CLI_CLIENT, []), { referenceId, stars: 1 }), /Only an editor or administrator/);
    // The Newsroom's own rating carries no note, and the delegated one still works.
    assert.equal((await backend.call("setReferenceStars", newsroomSession, { referenceId, stars: 3 })).stars, 3);
    assert.equal(backend.reference().starRatedBy, EDITOR);
    const request = await approved(backend);
    await relay(backend, "recordDelegatedStars", request, { stars: 4 });
    assert.match(String(backend.reference().starRatedBy), /via Claude \(delegation /);
  },
};

async function main() {
  const wanted = process.argv[2];
  const names = wanted ? [wanted] : Object.keys(behaviours);
  for (const name of names) {
    assert.ok(Object.hasOwn(behaviours, name), `unknown behaviour ${name}`);
    await behaviours[name]();
    console.log(`ok ${name}`);
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
