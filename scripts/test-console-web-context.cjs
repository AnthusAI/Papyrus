#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const ts = require("typescript");

registerTypeScriptRequire();

const {
  CONSOLE_WEB_CONTEXT_MESSAGE_KIND,
  formatConsoleWebContextMessage,
  readConsoleAgentInstructionsFromMessageMetadata,
  readConsoleWebUiFromMessageMetadata,
  webUiContextKey,
} = require("../lib/console-web-context.ts");

assert.equal(CONSOLE_WEB_CONTEXT_MESSAGE_KIND, "console_web_context");

const referenceWebUi = {
  webPath: "/newsroom/references/reference-knowledge-corpus-ai-ml-research-a47f3f11-18cb-4aa1-b69d-44c38026bfeb",
  papyrusLocationUri: "papyrus://newsroom/references/detail/reference-knowledge-corpus-ai-ml-research-a47f3f11-18cb-4aa1-b69d-44c38026bfeb",
  papyrusObjectUri: "papyrus://reference/reference-knowledge-corpus-ai-ml-research-a47f3f11-18cb-4aa1-b69d-44c38026bfeb",
  newsroomTab: "references",
  viewMode: "detail",
  indexFilters: null,
  label: "AgentBench",
};

const sessionStart = formatConsoleWebContextMessage(referenceWebUi, "session_start");
assert.match(sessionStart.visibleContent, /Console session started/);
assert.match(sessionStart.visibleContent, /papyrus:\/\/reference\//);
assert.match(sessionStart.agentInstructions, /Reference\.get/);
assert.match(sessionStart.agentInstructions, /do not ask them to paste the reference/);

const navigation = formatConsoleWebContextMessage(referenceWebUi, "navigation");
assert.match(navigation.visibleContent, /navigated to a new page/);

const metadata = {
  console: {
    webUi: referenceWebUi,
    contextEvent: "session_start",
    agentInstructions: sessionStart.agentInstructions,
  },
};

assert.deepEqual(readConsoleWebUiFromMessageMetadata(metadata), referenceWebUi);
assert.equal(
  readConsoleAgentInstructionsFromMessageMetadata(metadata),
  sessionStart.agentInstructions,
);

const keyA = webUiContextKey(referenceWebUi);
const keyB = webUiContextKey({ ...referenceWebUi, viewMode: "index" });
assert.notEqual(keyA, keyB);

console.log("test-console-web-context: ok");

function registerTypeScriptRequire() {
  require.extensions[".ts"] = function register(module, filename) {
    const source = require("node:fs").readFileSync(filename, "utf8");
    const output = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2020,
        esModuleInterop: true,
      },
      fileName: filename,
    }).outputText;
    module._compile(output, filename);
  };
}
