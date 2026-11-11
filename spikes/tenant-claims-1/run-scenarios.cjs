#!/usr/bin/env node
// Offline scenario runner (PPY-867f76). Executes the VTL resolvers Amplify generated (see synth.ts) against an
// in-memory table, with the simulator's AppSync VTL engine. No AWS call is made. It is NOT a substitute for a
// sandbox run: it proves what the generated authorization templates decide, not what AppSync, Cognito or the
// Lambda do. Usage:
//   SIM_DIR=<dir with node_modules/amplify-appsync-simulator> node run-scenarios.cjs <synth-outdir>
const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");
const req = createRequire(path.join(process.env.SIM_DIR || process.cwd(), "x.js"));
const { VelocityTemplate } = req("amplify-appsync-simulator/lib/velocity");
const { AmplifyAppSyncSimulatorAuthenticationType: AuthType } = req("amplify-appsync-simulator/lib/type-definition");

const out = process.argv[2];
const cache = new Map();
const asset = (hash) => fs.readFileSync(path.join(out, `asset.${hash}.vtl`), "utf8");
const loc = (v) => (typeof v === "string" ? v : (v["Fn::Sub"] ? asset(v["Fn::Sub"].match(/([0-9a-f]{64})\.vtl/)[1]) : join(v)));
const join = (v) => (typeof v === "string" ? v : v["Fn::Join"][1].map((p) => (typeof p === "string" ? p : "x")).join(""));

// ---- pipeline model from the synthesized nested templates
const resolvers = {};
for (const f of fs.readdirSync(out).filter((n) => n.endsWith(".nested.template.json") && !n.includes("TableManager"))) {
  const t = JSON.parse(fs.readFileSync(path.join(out, f), "utf8")).Resources;
  const fns = {};
  for (const [id, r] of Object.entries(t)) if (r.Type === "AWS::AppSync::FunctionConfiguration") {
    const p = r.Properties;
    fns[id] = { name: p.Name, req: loc(p.RequestMappingTemplateS3Location), res: p.ResponseMappingTemplateS3Location ? loc(p.ResponseMappingTemplateS3Location) : "$util.toJson($ctx.result)" };
  }
  for (const r of Object.values(t)) if (r.Type === "AWS::AppSync::Resolver") {
    const p = r.Properties;
    resolvers[`${p.TypeName}.${p.FieldName}`] = {
      fns: p.PipelineConfig.Functions.map((x) => fns[x["Fn::GetAtt"][0]]),
      reqT: join(p.RequestMappingTemplate), resT: join(p.ResponseMappingTemplate),
    };
  }
}

// ---- in-memory DynamoDB: tables per model, GSIs by attribute name
const unm = (v) => (v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 1 && /^(S|N|BOOL|NULL|L|M)$/.test(Object.keys(v)[0])
  ? (v.S ?? v.N ?? v.BOOL ?? (v.NULL ? null : v.L ? v.L.map(unm) : v.M)) : v);
function evalExpr(expr, names, values, item) {
  if (!expr) return true;
  let js = expr.replace(/attribute_exists\((#\w+)\)/g, (_, n) => `(item[${JSON.stringify(names[n])}]!==undefined)`)
    .replace(/attribute_not_exists\((#\w+)\)/g, (_, n) => `(item[${JSON.stringify(names[n])}]===undefined)`)
    .replace(/begins_with\((#\w+),\s*(:\w+)\)/g, (_, n, v) => `String(item[${JSON.stringify(names[n])}]??"").startsWith(vals[${JSON.stringify(v)}])`)
    .replace(/#\w+/g, (n) => `item[${JSON.stringify(names[n])}]`).replace(/:\w+/g, (v) => `vals[${JSON.stringify(v)}]`)
    .replace(/<>/g, "!==").replace(/(?<![<>!=])=(?!=)/g, "===").replace(/\bAND\b/g, "&&").replace(/\bOR\b/g, "||").replace(/\bNOT\b/g, "!");
  const vals = Object.fromEntries(Object.entries(values || {}).map(([k, v]) => [k, unm(v)]));
  return Boolean(new Function("item", "vals", `return ${js}`)(item, vals));
}
class Db {
  constructor() { this.rows = {}; }
  t(n) { return (this.rows[n] ??= new Map()); }
  exec(table, op) {
    const T = this.t(table);
    const key = op.key && unm(op.key.id);
    switch (op.operation) {
      case "GetItem": return T.get(key) ?? null;
      case "Scan": case "Query": {
        let items = [...T.values()];
        if (op.operation === "Query") {
          const q = op.query, nm = q.expressionNames || { "#id": "id" }, vs = Object.fromEntries(Object.entries(q.expressionValues).map(([k, v]) => [k, unm(v)]));
          items = items.filter((i) => evalExpr(q.expression.replace(/^id = /, "#id = "), nm, vs, i));
        }
        const limit = op.limit ?? 100;
        const page = items.slice(0, limit); // one page = `limit` rows READ; the filter then drops rows from the page
        const kept = op.filter ? page.filter((i) => evalExpr(op.filter.expression, op.filter.expressionNames, Object.fromEntries(Object.entries(op.filter.expressionValues || {}).map(([k, v]) => [k, unm(v)])), i)) : page;
        return { items: kept, scannedCount: page.length, nextToken: items.length > limit ? "more" : null };
      }
      case "PutItem": {
        const item = Object.fromEntries(Object.entries(op.attributeValues).map(([k, v]) => [k, unm(v)]));
        T.set(unm(op.key.id), item); return item;
      }
      case "UpdateItem": case "DeleteItem": {
        const cur = T.get(key);
        const c = op.condition;
        if (c && !evalExpr(c.expression, c.expressionNames, Object.fromEntries(Object.entries(c.expressionValues || {}).map(([k, v]) => [k, unm(v)])), cur ?? {})) throw Object.assign(new Error("ConditionalCheckFailed"), { type: "DynamoDB:ConditionalCheckFailedException" });
        if (op.operation === "DeleteItem") { T.delete(key); return cur; }
        const next = { ...cur };
        const u = op.update, nm = u.expressionNames, vs = u.expressionValues || {};
        const set = /SET (.*?)(?: REMOVE|$)/.exec(u.expression);
        if (set) for (const part of set[1].split(", ")) { const [n, v] = part.split(" = "); next[nm[n]] = unm(vs[v]); }
        const rem = /REMOVE (.*)$/.exec(u.expression);
        if (rem) for (const n of rem[1].split(", ")) delete next[nm[n]];
        T.set(key, next); return next;
      }
      default: throw new Error(`op ${op.operation}`);
    }
  }
}

const db = new Db();
const tableOf = (typeName) => typeName; // one table per model in this model
const INDEX_ATTR = { itemsByKey: "key", referencesByTkey: "tkey" };

// ---- run one GraphQL operation as a caller with the given access-token claims
function call(field, args, claims, model) {
  const r = resolvers[field];
  const rc = { jwt: claims, requestAuthorizationMode: AuthType.AMAZON_COGNITO_USER_POOLS, headers: {} };
  const sim = { appSyncConfig: { defaultAuthenticationType: { authenticationType: AuthType.AMAZON_COGNITO_USER_POOLS } } };
  const info = { fieldName: field.split(".")[1], parentTypeName: field.split(".")[0], variables: {}, fieldNodes: [{ name: { value: field.split(".")[1] } }], operation: { operation: "query" }, selectionSetList: [], selectionSetGraphQL: "" };
  const render = (src, ctx) => {
    try { return new VelocityTemplate({ content: src, path: "t" }, sim).render(ctx, rc, info); }
    catch (e) { return { hadException: true, errors: [{ message: `engine: ${e.message}` }], stash: ctx.stash, args: ctx.arguments }; }
  };
  const why = (errs) => { const e = errs && errs[errs.length - 1]; return e ? `${e.constructor && e.constructor.name !== "Object" ? e.constructor.name : "error"}${e.type ? ":" + e.type : ""}${e.message ? " " + e.message : ""}` : "template stopped"; };
  const base = { arguments: JSON.parse(JSON.stringify(args)), stash: { typeName: field.split(".")[0], fieldName: field.split(".")[1], conditions: [], metadata: { dataSourceType: "AMAZON_DYNAMODB" }, connectionAttributes: {}, tableName: model, adminRoles: [] } };
  let first = render(r.reqT, { ...base });
  let stash = first.stash, prev = {}, a = first.args;
  for (const fn of r.fns) {
    const q = render(fn.req, { arguments: a, stash, prevResult: prev });
    if (q.hadException) return { denied: true, why: `${fn.name}: ${why(q.errors)}` };
    stash = q.stash; a = q.args;
    let result;
    const op = q.result;
    if (op && op.operation) {
      try { result = db.exec(model, op); } catch (e) { return { denied: true, why: e.message }; }
      if (op.operation === "Query" && op.index) { /* index key is applied by expression names inside exec */ }
    } else result = op && op.payload !== undefined ? op.payload : op;
    const s = render(fn.res, { arguments: a, stash, prevResult: prev, result, error: undefined });
    if (s.hadException) return { denied: true, why: `${fn.name}: ${why(s.errors)}` };
    stash = s.stash; a = s.args; prev = s.result;
  }
  return { denied: false, data: prev };
}

// ---- scenarios
let pass = 0, fail = 0;
const check = (name, ok, detail) => { (ok ? pass++ : fail++); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`); };
const A = { sub: "u-a", "cognito:username": "a", papyrus_tenant_editor: "alpha" };
const B = { sub: "u-b", "cognito:username": "b", papyrus_tenant_editor: "beta" };
const Amember = { sub: "u-m", "cognito:username": "m", papyrus_tenant_member: "alpha" };
const NOCLAIM = { sub: "u-n", "cognito:username": "n" };
const seed = (model, id, tenantId, extra) => db.t(model).set(id, { id, tenantId, ...extra });
const summary = (r) => (r.denied ? `denied: ${r.why}` : `ok: ${JSON.stringify(r.data)}`);
const empty = (r) => r.denied || r.data == null || (r.data.items && r.data.items.length === 0);

for (const [Model, lc, idxField, idxAttr, keyArg] of [["Item", "Item", "listItemByKey", "key", "key"], ["Reference", "Reference", "listReferenceByTkey", "tkey", "tkey"]]) {
  seed(Model, `${Model}-alpha`, "alpha", { title: "a", [idxAttr]: "alpha#1" });
  seed(Model, `${Model}-beta`, "beta", { title: "b", [idxAttr]: "beta#1" });
  const tag = (s) => `${Model}: ${s}`;
  let r = call(`Query.get${Model}`, { id: `${Model}-beta` }, A, Model);
  check(tag("alpha editor gets beta's row"), empty(r), summary(r));
  r = call(`Query.get${Model}`, { id: `${Model}-alpha` }, A, Model);
  check(tag("alpha editor gets alpha's own row (control)"), !r.denied && r.data && r.data.tenantId === "alpha", summary(r));
  r = call(`Query.list${Model}s`, {}, A, Model);
  check(tag("alpha editor lists: only alpha rows come back"), !r.denied && r.data.items.every((i) => i.tenantId === "alpha") && r.data.items.length === 1, summary(r));
  r = call(`Query.list${Model}s`, { filter: { tenantId: { eq: "beta" } } }, A, Model);
  check(tag("alpha editor lists with filter tenantId=beta"), empty(r), summary(r));
  r = call(`Query.${idxField}`, { [keyArg]: "beta#1" }, A, Model);
  check(tag("alpha editor lists the index at beta's key"), empty(r), summary(r));
  r = call(`Query.${idxField}`, { [keyArg]: "alpha#1" }, A, Model);
  check(tag("alpha editor lists the index at alpha's key (control)"), !r.denied && r.data.items.length === 1, summary(r));
  r = call(`Mutation.create${Model}`, { input: { id: `${Model}-x`, tenantId: "beta", title: "evil" } }, A, Model);
  check(tag("alpha editor creates with tenantId beta"), r.denied, summary(r));
  r = call(`Mutation.create${Model}`, { input: { id: `${Model}-y`, tenantId: "alpha", title: "ok" } }, A, Model);
  check(tag("alpha editor creates with tenantId alpha (control)"), !r.denied, summary(r));
  r = call(`Mutation.update${Model}`, { input: { id: `${Model}-beta`, title: "hacked" } }, A, Model);
  check(tag("alpha editor updates beta's row"), r.denied, summary(r));
  r = call(`Mutation.delete${Model}`, { input: { id: `${Model}-beta` } }, A, Model);
  check(tag("alpha editor deletes beta's row"), r.denied, summary(r));
  check(tag("beta's row is untouched afterwards"), db.t(Model).get(`${Model}-beta`).title === "b");
  for (const op of ["get", "list"]) {
    r = call(op === "get" ? `Query.get${Model}` : `Query.list${Model}s`, op === "get" ? { id: `${Model}-alpha` } : {}, NOCLAIM, Model);
    check(tag(`a token with no tenant claim cannot ${op}`), empty(r), summary(r));
  }
  r = call(`Mutation.create${Model}`, { input: { id: `${Model}-z`, tenantId: "alpha" } }, NOCLAIM, Model);
  check(tag("a token with no tenant claim cannot create"), r.denied, summary(r));
  r = call(`Mutation.create${Model}`, { input: { id: `${Model}-m`, tenantId: "alpha" } }, Amember, Model);
  check(tag("an alpha MEMBER (read-only role) cannot create in alpha"), r.denied, summary(r));
  r = call(`Mutation.update${Model}`, { input: { id: `${Model}-alpha`, title: "m" } }, Amember, Model);
  check(tag("an alpha MEMBER cannot update alpha's row"), r.denied, summary(r));
  r = call(`Query.get${Model}`, { id: `${Model}-alpha` }, Amember, Model);
  check(tag("an alpha MEMBER can read alpha's row (control)"), !r.denied && r.data && r.data.tenantId === "alpha", summary(r));
  r = call(`Mutation.update${Model}`, { input: { id: `${Model}-alpha`, tenantId: "beta" } }, A, Model);
  const moved = db.t(Model).get(`${Model}-alpha`).tenantId;
  // FINDING, not a pass/fail expectation of the design: with model-level rules only, the update is ALLOWED and the row
  // leaves alpha for beta. The check passes when that hole is reproduced, so a future Amplify fix shows up as a failure here.
  check(tag("FINDING: alpha editor can move alpha's row into tenantId beta (model-level rules only)"), !r.denied && moved === "beta", `stored tenantId is now ${moved}`);
}

// Field-level rule: tenantId create+read only
seed("ItemLocked", "L-alpha", "alpha", { title: "a" });
let r = call("Mutation.createItemLocked", { input: { id: "L-new", tenantId: "alpha", title: "x" } }, A, "ItemLocked");
check("ItemLocked: alpha editor creates with tenantId alpha (field rule allows create)", !r.denied, summary(r));
r = call("Mutation.updateItemLocked", { input: { id: "L-alpha", tenantId: "beta" } }, A, "ItemLocked");
check("ItemLocked: alpha editor moves its row to beta (field rule: no update)", r.denied, `${summary(r)}; stored tenantId is ${db.t("ItemLocked").get("L-alpha").tenantId}`);
r = call("Mutation.updateItemLocked", { input: { id: "L-alpha", title: "renamed" } }, A, "ItemLocked");
check("ItemLocked: alpha editor still updates the title (control)", !r.denied, summary(r));
r = call("Mutation.updateItemLocked", { input: { id: "L-alpha", tenantId: "alpha", title: "same-tenant resend" } }, A, "ItemLocked");
console.log(`INFO  ItemLocked: update that re-sends tenantId=alpha: ${summary(r)}`);

// Subscriptions: the generated filter
// Subscriptions are read from the generated templates (see the findings note), not executed here: the simulator cannot run
// $extensions.setSubscriptionFilter, which is where AppSync applies the per-tenant filter.

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
