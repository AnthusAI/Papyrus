/**
 * Every function takes its tenant from the caller (PPY-7dc463). The function list is the schema's (readFunctions in
 * scripts/generate-tenant-isolation-cases.ts: the directories under amplify/functions and each plugin's function directory), so a new function
 * that is neither moved nor named on the pending list fails here. A moved handler builds its one TenantContext from the event and never reads the
 * tenant from the environment; the TypeScript handlers are run on a shared stack and must refuse a call that cannot name one tenant.
 * Python handlers are run by procedures/newsroom/tests/test_function_tenant_context.py from the same list.
 */
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { readFunctions } from "./generate-tenant-isolation-cases";
import { readSchema } from "./lib/schema-reader";
import { TENANCY_MODE_ENVIRONMENT_VARIABLE, TENANT_FIELD_MODELS, TENANT_ID_ENVIRONMENT_VARIABLE, TENANT_MODELS } from "../lib/tenant-keys";
import { TenantContextRefusal } from "../amplify/functions/shared/tenant-context";

const ROOT = path.resolve(import.meta.dirname, "..");
const registry = JSON.parse(readFileSync(path.join(ROOT, "features_backend/fixtures/function-tenant-context/handlers.json"), "utf8")) as {
  moved: string[];
  pending: Record<string, string>;
};
const functions = readFunctions(ROOT);

/** What a handler must not read: the tenant belongs to the call's context, not the build or the process. */
const FORBIDDEN = [
  "PAPYRUS_TENANT_ID", "PAPYRUS_SINGLE_PUBLICATION_BACKEND", "tenantIdFromEnvironment", "tenant_id_from_environment", "configured_tenant_id", "site_tenant_id",
  "TENANT_ID_ENVIRONMENT_VARIABLE", "process.env.PAPYRUS_TENANT",
];
const BUILDERS = ["buildEventTenantContext", "build_event_tenant_context"];

function sources(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory)) {
    const full = path.join(directory, entry);
    if (entry === "node_modules" || entry === "target" || entry === "__pycache__") continue;
    if (statSync(full).isDirectory()) found.push(...sources(full));
    else if (/\.(py|ts|tsx)$/.test(entry) && !/(_test\.py|\.test\.[a-z]+|test_.*\.py)$/.test(entry)) found.push(full);
  }
  return found;
}

const infoOf = (directory: string) => functions.find((info) => info.directory === directory)!;
const handlerFile = (directory: string) => ["handler.py", "handler.ts"].map((name) => path.join(ROOT, infoOf(directory).relativePath, name)).find(existsSync);

test("every function of the schema's function list is moved or on the pending list, once", () => {
  const listed = [...registry.moved, ...Object.keys(registry.pending)];
  const missing = functions.map((info) => info.directory).filter((directory) => !listed.includes(directory));
  assert.deepEqual(missing, [], `function(s) with no tenant context and no pending entry: ${missing.join(", ")}. Build the context in the handler (docs/multi-tenancy.md) and add it to "moved" in features_backend/fixtures/function-tenant-context/handlers.json`);
  assert.deepEqual(listed.filter((name, index) => listed.indexOf(name) !== index), [], "a function is both moved and pending, or listed twice");
  const unknown = listed.filter((directory) => !functions.some((info) => info.directory === directory));
  assert.deepEqual(unknown, [], `listed but not a function any more: ${unknown.join(", ")}`);
});

test("every pending function names the board sub-task that moves it", () => {
  for (const [directory, task] of Object.entries(registry.pending)) assert.match(task, /^PPY-[0-9a-f]{6}$/, `${directory} needs a sub-task of PPY-7dc463`);
});

test("a function that already builds its context is not on the pending list", () => {
  for (const directory of Object.keys(registry.pending)) {
    const file = handlerFile(directory);
    if (!file) continue;
    assert.ok(!BUILDERS.some((builder) => readFileSync(file, "utf8").includes(builder)), `${directory} builds its context: remove it from "pending"`);
  }
});

test("a moved handler builds one TenantContext from the event", () => {
  for (const directory of registry.moved) {
    const file = handlerFile(directory);
    assert.ok(file, `${directory} has no handler.py or handler.ts`);
    const text = readFileSync(file, "utf8");
    assert.equal(BUILDERS.filter((builder) => text.includes(builder)).length, 1, `${directory}/${path.basename(file)} builds its context with exactly one builder call`);
  }
});

test("no source file of a moved function reads the tenant from the environment", () => {
  for (const directory of registry.moved) {
    for (const file of sources(path.join(ROOT, infoOf(directory).relativePath))) {
      const text = readFileSync(file, "utf8");
      for (const name of FORBIDDEN) assert.ok(!text.includes(name), `${path.relative(ROOT, file)} reads ${name}: take the tenant from the TenantContext`);
    }
  }
});

test("the model lists of the TypeScript scoped client are the schema's tenant models", () => {
  // The tenancy record models (docs/multi-tenancy.md, "Tenancy records") are the platform's own, written by the operator role (PPY-203ce2), not by a tenant's function.
  const platformRecords = ["SiteDocument", "SiteDocumentVersion", "TenantDomain", "TenantMembership"];
  const withTenant = readSchema().models.filter((model) => model.hasTenantId && !platformRecords.includes(model.name)).map((model) => model.name).sort();
  assert.deepEqual([...TENANT_MODELS, ...TENANT_FIELD_MODELS].sort(), withTenant);
  const python = readFileSync(path.join(ROOT, "src/papyrus_content/tenancy.py"), "utf8");
  const listed = (name: string) => {
    const block = new RegExp(`${name} = frozenset\\(\\s*\\{(.*?)\\}\\s*\\)`, "s").exec(python)![1];
    return [...block.matchAll(/"([A-Za-z]+)"/g)].map((match) => match[1]).sort();
  };
  assert.deepEqual(listed("TENANT_MODELS"), [...TENANT_MODELS].sort());
  assert.deepEqual(listed("TENANT_FIELD_MODELS"), [...TENANT_FIELD_MODELS].sort());
});

// The TypeScript handlers, run on a shared stack with events that cannot name one tenant.
const IAM = { accountId: "000000000000", userArn: "arn:aws:iam::000000000000:role/operator" };
const user = (claims: Record<string, unknown>) => ({ sub: "user-1", claims: { sub: "user-1", ...claims } });

async function refusal(directory: string, identity: unknown, environment: Record<string, string>): Promise<string> {
  const saved = Object.fromEntries(Object.keys(environment).map((name) => [name, process.env[name]]));
  Object.assign(process.env, environment);
  try {
    const { handler } = await import(handlerFile(directory)!);
    await handler({ info: { fieldName: "getNewsroomSummary" }, fieldName: "getNewsroomSummary", arguments: {}, identity });
    return "none";
  } catch (error) {
    return (error as Error).name === "TenantContextRefusal" ? (error as TenantContextRefusal).reason : `other: ${(error as Error).message}`;
  } finally {
    for (const [name, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
}

const shared = { [TENANCY_MODE_ENVIRONMENT_VARIABLE]: "shared" };
for (const directory of registry.moved.filter((name) => handlerFile(name)?.endsWith(".ts"))) {
  test(`${directory}: a shared stack refuses an IAM call that names no tenant before any read`, async () => {
    assert.equal(await refusal(directory, IAM, shared), "iam_without_tenant");
  });
  test(`${directory}: a shared stack refuses a token with no tenant claim`, async () => {
    assert.equal(await refusal(directory, user({}), shared), "no_tenant_claim");
  });
  test(`${directory}: a shared stack refuses claims that name two tenants`, async () => {
    assert.equal(await refusal(directory, user({ papyrus_tenant_admin: "alpha", papyrus_tenant_member: "beta" }), shared), "multiple_tenants");
  });
  test(`${directory}: a dedicated stack refuses a claim for another tenant than its own`, async () => {
    assert.equal(await refusal(directory, user({ papyrus_tenant_editor: "beta" }), { [TENANT_ID_ENVIRONMENT_VARIABLE]: "alpha" }), "foreign_tenant");
  });
}
