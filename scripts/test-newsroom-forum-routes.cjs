#!/usr/bin/env node

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

require("./register-papyrus-aliases.cjs");
registerTypeScriptRequire();

const {
  buildForumThreadUrl,
  getForumMessageAnchorId,
  isForumThreadId,
  parseForumMessageAnchorFromHash,
  parseNewsroomForumRoute,
} = require("../lib/newsroom-forum-routes.ts");

assert.equal(isForumThreadId("message-thread-edition-forum-2026-06-05"), true);
assert.equal(isForumThreadId("message-demo-1"), false);

const threadId = "message-thread-section-forum-culture";
const messageId = "message-forum/message-thread-section-forum-culture-0002";
const anchor = getForumMessageAnchorId(messageId);
assert.equal(anchor.startsWith("message-"), true);
assert.equal(parseForumMessageAnchorFromHash(`#${anchor}`), messageId);

const canonical = buildForumThreadUrl(threadId, { messageId });
assert.equal(
  canonical,
  `/newsroom/forum/${encodeURIComponent(threadId)}#${anchor}`,
);

assert.deepEqual(
  parseNewsroomForumRoute(`/newsroom/forum/${encodeURIComponent(threadId)}`, `#${anchor}`),
  { threadId, messageId },
);

assert.deepEqual(
  parseNewsroomForumRoute(`/newsroom/messages/forum/${encodeURIComponent(threadId)}`, `#${anchor}`),
  { threadId, messageId },
);

assert.deepEqual(
  parseNewsroomForumRoute(`/newsroom/messages/${encodeURIComponent(threadId)}`, ""),
  { threadId, messageId: null },
);

console.log("newsroom forum route tests passed");

function registerTypeScriptRequire() {
  const compilerOptions = {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    esModuleInterop: true,
    jsx: ts.JsxEmit.React,
    moduleResolution: ts.ModuleResolutionKind.Node10,
  };
  require.extensions[".ts"] = function registerTsExtension(module, filename) {
    const source = fs.readFileSync(filename, "utf8");
    const output = ts.transpileModule(source, {
      compilerOptions,
      fileName: filename,
    }).outputText;
    return module._compile(output, filename);
  };
  require.extensions[".tsx"] = require.extensions[".ts"];
}
