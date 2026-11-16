// The origin-response function of the edge template answers a miss under a language prefix with that language's 404 page (features: language editions, docs/multilingual-serving.md).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import vm from "node:vm";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function functionFrom(templateFile, prefixes) {
  const text = fs.readFileSync(templateFile, "utf8");
  const code = text.split("ZipFile: !Sub |\n")[1].split("\n  NotFoundPageVersion:")[0];
  const lines = code.split("\n").map((line) => line.replace(/^ {10}/, ""));
  const source = lines.join("\n").replace("${LanguagePrefixes}", prefixes);
  const fetched = [];
  const pages = { "/404.html": "ENGLISH 404", "/es/404.html": "SPANISH 404" };
  const https = {
    get({ host, path: requested }, callback) {
      fetched.push(requested);
      const handlers = {};
      const response = { statusCode: requested in pages ? 200 : 404, on: (name, handler) => { handlers[name] = handler; } };
      setImmediate(() => { callback(response); handlers.data?.(Buffer.from(pages[requested] ?? "")); handlers.end?.(); });
      return { on() {}, destroy() {} };
    },
  };
  const module = { exports: {} };
  vm.runInNewContext(source, { require: (name) => (name === "https" ? https : createRequire(import.meta.url)(name)), exports: module.exports, Buffer, setImmediate });
  return { handler: module.exports.handler, fetched };
}

async function miss(handler, uri) {
  const event = { Records: [{ cf: { request: { uri }, response: { status: "403", headers: {} }, config: { distributionDomainName: "d.example" } } }] };
  return handler(event);
}

for (const template of ["infra/edge/s3-projection-cms.yaml"]) {
  const file = path.join(root, template);
  const { handler, fetched } = functionFrom(file, "es,zh");
  assert.equal((await miss(handler, "/es/zzz")).body, "SPANISH 404");
  assert.deepEqual(fetched.slice(-1), ["/es/404.html"]);
  assert.equal((await miss(handler, "/zzz")).body, "ENGLISH 404");
  assert.equal((await miss(handler, "/zh/zzz")).body, "ENGLISH 404", "a language with no 404 page of its own gets the site's");
  assert.deepEqual(fetched.slice(-2), ["/zh/404.html", "/404.html"]);
  assert.equal((await miss(handler, "/es/404.html")).body, "Not found", "a missing 404 page never loops");
  const none = functionFrom(file, "");
  assert.equal((await miss(none.handler, "/es/zzz")).body, "ENGLISH 404", "no prefixes: every miss is the site's 404");
  assert.equal((await miss(handler, "/es/zzz")).status, "404");
}
console.log("edge language 404 ok");
