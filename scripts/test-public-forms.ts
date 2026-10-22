import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { a } from "@aws-amplify/backend";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { schema, schemaExcludingGroups, schemaWithPlugins } from "../amplify/data/schema";
import { publicForms } from "../amplify/functions/public-forms/resource";
import { derivePublicFormOrigins } from "../amplify/functions/public-forms/origins";
import { wirePublicForms } from "../amplify/functions/public-forms/wire";
import {
  DEFAULT_PUBLIC_FORMS_CONFIG,
  handlePublicFormRequest,
  parseOrigins,
  type FormSubmissionRecord,
  type FunctionUrlEvent,
  type PublicFormsConfig,
  type RateLimiter,
} from "../amplify/functions/public-forms/core";

const ORIGIN = "https://distinctive-mark.com";
const config: PublicFormsConfig = { ...DEFAULT_PUBLIC_FORMS_CONFIG, allowedOrigins: [ORIGIN] };

function harness(overrides: Partial<PublicFormsConfig> = {}, failStore = false) {
  const saved: FormSubmissionRecord[] = [];
  const counts = new Map<string, number>();
  const limiter: RateLimiter = {
    async hit(scope, subject, windowSeconds, limit) {
      const key = `${scope}#${subject}#${windowSeconds}`;
      const next = (counts.get(key) ?? 0) + 1;
      counts.set(key, next);
      return next <= limit;
    },
  };
  const deps = {
    store: {
      async save(record: FormSubmissionRecord) {
        if (failStore) throw new Error("down");
        saved.push(record);
      },
    },
    limiter,
    now: () => new Date("2026-10-21T12:00:00Z"),
    newId: () => `form-test-${saved.length + 1}`,
  };
  return { saved, call: (event: FunctionUrlEvent) => handlePublicFormRequest(event, { ...config, ...overrides }, deps) };
}

function post(body: unknown, extra: Partial<FunctionUrlEvent> & { origin?: string | null; ip?: string } = {}): FunctionUrlEvent {
  const { origin = ORIGIN, ip = "203.0.113.7", ...rest } = extra;
  return {
    headers: { "content-type": "application/json", ...(origin === null ? {} : { origin }) },
    body: typeof body === "string" ? body : JSON.stringify(body),
    requestContext: { http: { method: "POST", sourceIp: ip } },
    ...rest,
  };
}

const valid = { form: "contact", topic: "Report an error", name: "Ada", email: "ada@example.org", message: "Typo in the third paragraph.", page: "/articles/x/", website: "" };

async function main() {
  // A valid submission creates a Message.
  {
    const { saved, call } = harness();
    const result = await call(post(valid));
    assert.equal(result.statusCode, 200);
    assert.equal(result.headers["Access-Control-Allow-Origin"], ORIGIN);
    assert.deepEqual(JSON.parse(result.body), { ok: true });
    assert.equal(saved.length, 1);
    const [record] = saved;
    assert.equal(record.messageKind, "form_submission");
    assert.equal(record.status, "active");
    assert.equal(record.searchVisibility, "private");
    assert.equal(record.createdAt, "2026-10-21T12:00:00.000Z");
    const metadata = JSON.parse(record.metadata);
    assert.equal(metadata.formId, "contact");
    assert.equal(metadata.topic, "Report an error");
    assert.equal(metadata.page, "/articles/x/");
    assert.equal(metadata.fields.email, "ada@example.org");
    assert.equal(metadata.origin, ORIGIN);
    assert.match(record.content, /Typo in the third paragraph\./);
    assert.ok(!result.body.includes("Ada"), "the answer must not reflect input");
  }
  // A suggestion on a wiki page reaches the newsroom as a private message that names the page, and answers without changing anything.
  {
    const { saved, call } = harness();
    const result = await call(post({ message: "The founding year is wrong.", page: "/wiki/maker-acme-loom/", website: "" }, { rawQueryString: "form=suggest-edit" }));
    assert.equal(result.statusCode, 200);
    assert.deepEqual(JSON.parse(result.body), { ok: true });
    const [record] = saved;
    assert.equal(record.searchVisibility, "private");
    assert.equal(JSON.parse(record.metadata).formId, "suggest-edit");
    assert.equal(JSON.parse(record.metadata).page, "/wiki/maker-acme-loom/");
    assert.match(record.content, /Form: suggest-edit/);
    assert.match(record.content, /page: \/wiki\/maker-acme-loom\//);
    assert.match(record.content, /The founding year is wrong\./);
  }
  // Newsletter signups share the endpoint (form id in the body or the query string).
  {
    const { saved, call } = harness();
    assert.equal((await call(post({ form: "newsletter", email: "reader@example.org" }))).statusCode, 200);
    assert.equal((await call(post({ email: "other@example.org" }, { rawQueryString: "form=newsletter" }))).statusCode, 200);
    assert.equal(saved.length, 2);
    for (const record of saved) {
      assert.equal(record.messageKind, "form_submission");
      assert.equal(record.messageType, "newsletter_signup");
      assert.equal(JSON.parse(record.metadata).formId, "newsletter");
    }
    assert.equal((await call(post({ form: "newsletter", message: "no email" }))).statusCode, 400);
  }
  // Without a form id the submission is a contact form.
  {
    const { saved, call } = harness();
    await call(post({ message: "hello" }));
    assert.equal(JSON.parse(saved[0].metadata).formId, "contact");
  }
  // The honeypot answers 200 and stores nothing.
  {
    const { saved, call } = harness();
    const result = await call(post({ ...valid, website: "http://spam.example" }));
    assert.equal(result.statusCode, 200);
    assert.equal(saved.length, 0);
  }
  // Rate limits: per address, per form, per site.
  {
    const { saved, call } = harness({ ipLimit: 2 });
    assert.equal((await call(post(valid))).statusCode, 200);
    assert.equal((await call(post(valid))).statusCode, 200);
    const limited = await call(post(valid));
    assert.equal(limited.statusCode, 429);
    assert.ok(limited.headers["Retry-After"]);
    assert.equal(saved.length, 2);
    assert.equal((await call(post(valid, { ip: "198.51.100.9" }))).statusCode, 200, "another address is unaffected");
  }
  {
    const { saved, call } = harness({ formLimitPerHour: 1 });
    assert.equal((await call(post(valid, { ip: "198.51.100.1" }))).statusCode, 200);
    assert.equal((await call(post(valid, { ip: "198.51.100.2" }))).statusCode, 429);
    assert.equal((await call(post({ ...valid, form: "sponsor" }, { ip: "198.51.100.3" }))).statusCode, 200, "another form has its own budget");
    assert.equal(saved.length, 2);
  }
  {
    const { call } = harness({ siteLimitPerHour: 1 });
    assert.equal((await call(post({ ...valid, form: "a" }, { ip: "198.51.100.1" }))).statusCode, 200);
    assert.equal((await call(post({ ...valid, form: "b" }, { ip: "198.51.100.2" }))).statusCode, 429, "inventing form ids does not escape the site budget");
  }
  // A foreign or missing origin is refused and never stored.
  {
    const { saved, call } = harness();
    for (const origin of ["https://evil.example", "http://distinctive-mark.com", "https://distinctive-mark.com.evil.example", null]) {
      const result = await call(post(valid, { origin }));
      assert.equal(result.statusCode, 403, String(origin));
      assert.equal(result.headers["Access-Control-Allow-Origin"], undefined);
    }
    assert.equal(saved.length, 0);
  }
  // Preflight: allowed origin only.
  {
    const { call } = harness();
    const ok = await call({ headers: { origin: ORIGIN }, requestContext: { http: { method: "OPTIONS" } } });
    assert.equal(ok.statusCode, 204);
    assert.equal(ok.headers["Access-Control-Allow-Origin"], ORIGIN);
    assert.equal((await call({ headers: { origin: "https://evil.example" }, requestContext: { http: { method: "OPTIONS" } } })).statusCode, 403);
  }
  // No configured origins: nothing is accepted.
  {
    const { call } = harness({ allowedOrigins: [] });
    assert.equal((await call(post(valid))).statusCode, 403);
  }
  // Oversized and malformed bodies.
  {
    const { saved, call } = harness();
    assert.equal((await call(post({ ...valid, message: "x".repeat(20 * 1024) }))).statusCode, 413);
    assert.equal((await call(post({ ...valid, message: "x".repeat(5001) }))).statusCode, 400);
    const many = Object.fromEntries(Array.from({ length: 25 }, (_, index) => [`f${index}`, "v"]));
    assert.equal((await call(post(many))).statusCode, 400);
    assert.equal((await call(post("not json"))).statusCode, 400);
    assert.equal((await call(post("[1]"))).statusCode, 400);
    assert.equal((await call(post({ ...valid, email: "nope" }))).statusCode, 400);
    assert.equal((await call(post({ ...valid, name: 5 }))).statusCode, 400);
    assert.equal((await call(post({ ...valid, form: "Bad Form!" }))).statusCode, 400);
    assert.equal((await call(post({ form: "contact" }))).statusCode, 400);
    assert.equal((await call({ ...post(valid), headers: { origin: ORIGIN, "content-type": "text/plain" } })).statusCode, 415);
    assert.equal((await call({ ...post(valid), requestContext: { http: { method: "GET" } } })).statusCode, 405);
    assert.equal(saved.length, 0);
  }
  // A failing store is an error, never a fake success.
  {
    const { call } = harness({}, true);
    assert.equal((await call(post(valid))).statusCode, 500);
  }
  // Allow-list parsing is strict.
  assert.deepEqual(parseOrigins("https://a.example/path, http://b.example, not a url, http://localhost:3000"), ["https://a.example", "http://localhost:3000"]);

  // Editors-only: Message grants nothing to guests or API keys, and the endpoint's function may only mutate.
  for (const file of ["amplify/data/schema.ts", "amplify/data/resource.ts"]) {
    const source = readFileSync(join(process.cwd(), file), "utf8");
    const start = source.search(/^  Message: (a|realtimeModel)/m);
    assert.ok(start >= 0, `${file}: Message model`);
    const block = source.slice(start, source.search(/^  MessageThread: /m));
    assert.ok(block.includes('allow.groups(categoryWriteGroups)'), `${file}: editors and admins`);
    assert.ok(!/allow\.guest|allow\.publicApiKey|allow\.public\(/.test(block), `${file}: Message is never public`);
    assert.ok(source.includes('allow.resource(publicForms).to(["mutate"])'), `${file}: the endpoint function may only mutate`);
  }
  // Every deployed schema composition keeps the endpoint function's create-only access, with or without plugins.
  {
    const plugin = { Note: a.model({ body: a.string() }).authorization((allow) => [allow.groups(["admins"])]) };
    for (const [name, definition] of [
      ["base", schema],
      ["plugins", schemaWithPlugins(plugin)],
      ["no plugins, groups excluded", schemaExcludingGroups(["editions"])],
      ["plugins, groups excluded", schemaExcludingGroups(["editions"], plugin)],
    ] as const) {
      const grants = definition.transform().functionSchemaAccess.filter((access) => access.resourceProvider === publicForms);
      assert.equal(grants.length, 1, `${name}: the public-forms function needs a schema grant`);
      assert.deepEqual(grants[0].actions, ["mutate"], `${name}: the public-forms function may only mutate`);
    }
  }
  // The site's own origins are derived, never wildcards; bad explicit entries fail the deploy.
  assert.deepEqual(
    derivePublicFormOrigins({
      explicit: ["https://www.distinctive-mark.com", "http://localhost:3000"],
      hosts: ["distinctive-mark.com", undefined, ""],
      urls: ["https://cms.distinctive-mark.com/newsroom/", "http://localhost:3000/newsroom", "not a url"],
    }),
    ["http://localhost:3000", "https://cms.distinctive-mark.com", "https://distinctive-mark.com", "https://www.distinctive-mark.com"],
  );
  assert.throws(() => derivePublicFormOrigins({ explicit: ["*"] }), /allowedOrigins/);
  assert.throws(() => derivePublicFormOrigins({ explicit: ["http://example.org"] }), /allowedOrigins/);

  // The deploy wiring: a TTL counter table, a public Function URL, update-only access, origins in the environment.
  {
    const stack = new Stack(new App(), "Forms");
    const lambda = new LambdaFunction(stack, "Fn", { runtime: Runtime.NODEJS_22_X, handler: "index.handler", code: Code.fromInline("exports.handler=()=>{}") });
    const environment: Record<string, string> = {};
    const url = wirePublicForms(
      { publicForms: { resources: { lambda }, addEnvironment: (name, value) => { environment[name] = value; } } },
      { allowedOrigins: ["https://distinctive-mark.com"] },
    );
    assert.ok(url.length > 0);
    const template = Template.fromStack(stack);
    template.hasResourceProperties("AWS::DynamoDB::Table", { TimeToLiveSpecification: { AttributeName: "expiresAt", Enabled: true }, BillingMode: "PAY_PER_REQUEST" });
    template.hasResourceProperties("AWS::Lambda::Url", { AuthType: "NONE" });
    assert.equal(environment.PAPYRUS_PUBLIC_FORMS_ORIGINS, "https://distinctive-mark.com");
    assert.ok(environment.PAPYRUS_PUBLIC_FORMS_TABLE);
    const policies = JSON.stringify(template.findResources("AWS::IAM::Policy"));
    assert.ok(policies.includes("dynamodb:UpdateItem"));
    assert.ok(!/dynamodb:(Get|Query|Scan|Delete|Put|\*)/.test(policies), "the counters are update-only");
  }
  console.log("test-public-forms: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
