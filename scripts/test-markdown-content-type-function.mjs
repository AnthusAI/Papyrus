import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// PPY-40f96a: a browser is shown a Markdown twin as text/plain, a client that prefers text/markdown keeps it. The same
// scenarios are written in features/markdown-twin-display.feature.
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");
const source = fs.readFileSync(path.join(root, "amplify/publication/markdown-content-type.js"), "utf8");
const handler = new Function(`${source}\nreturn handler;`)();

const SAFARI = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8";

function respond(contentType, accept, extra = {}) {
  const headers = { ...(contentType === undefined ? {} : { "content-type": { value: contentType } }), ...extra };
  const request = { uri: "/x/index.md", headers: accept === undefined ? {} : { accept: { value: accept } } };
  return handler({ request, response: { statusCode: 200, headers } }).headers;
}

const stored = "text/markdown; charset=utf-8";

// a browser navigation is shown the text
for (const accept of [SAFARI, "text/html", "text/html,*/*;q=0.8", "TEXT/HTML, text/markdown;q=0.5"]) {
  assert.equal(respond(stored, accept)["content-type"].value, "text/plain; charset=utf-8", accept);
}

// a client that prefers Markdown, or names no type, keeps text/markdown
for (const accept of ["text/markdown", "text/markdown, text/html;q=0.5", "text/markdown,text/html", "*/*", undefined, "", "application/json"]) {
  assert.equal(respond(stored, accept)["content-type"].value, stored, String(accept));
}

// a response that is not Markdown is not touched, and nothing sets an attachment header
const html = respond("text/html; charset=utf-8", SAFARI);
assert.equal(html["content-type"].value, "text/html; charset=utf-8");
assert.equal(html.vary, undefined);
assert.equal(respond(undefined, SAFARI)["content-type"], undefined);
for (const accept of [SAFARI, "text/markdown"]) {
  assert.equal(respond(stored, accept)["content-disposition"], undefined);
}

// the cached object and its cache key are untouched: the function answers per viewer and only says what it varies on
assert.equal(respond(stored, SAFARI).vary.value, "Accept");
assert.equal(respond(stored, "text/markdown").vary.value, "Accept");
assert.equal(respond(stored, SAFARI, { vary: { value: "Accept-Encoding" } }).vary.value, "Accept-Encoding, Accept");
assert.equal(respond(stored, SAFARI, { vary: { value: "accept, Origin" } }).vary.value, "accept, Origin");

// the function is the same text wherever a hand-run edge template carries it
for (const template of ["s3-projection-cms", "pilobol-us", "threat-intelligence"]) {
  const text = fs.readFileSync(path.join(root, "infra/edge", `${template}.yaml`), "utf8");
  const indented = source.split("\n").map((line) => (line === "" ? line : `        ${line}`)).join("\n");
  assert.ok(text.includes(indented), `${template}.yaml carries amplify/publication/markdown-content-type.js`);
  assert.match(text, /EventType: viewer-response\n\s+FunctionARN: !GetAtt MarkdownContentTypeFunction\.FunctionARN/, template);
}

// anth-us-s3 keeps its own viewer-response function (previous-host headers) and applies the same rule
const anth = fs.readFileSync(path.join(root, "infra/edge/anth-us-s3.yaml"), "utf8");
assert.ok(anth.includes('headers["content-type"] = { value: "text/plain; charset=utf-8" };'));

console.log("markdown-content-type function ok");
