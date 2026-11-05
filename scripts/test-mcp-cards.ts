import assert from "node:assert/strict";
import { listMcpAppResources, readMcpAppResource, withMcpAppMetadata, withMcpAppResult } from "../lib/mcp/cards";

const resources = listMcpAppResources();
assert.equal(resources.length, 2);
for (const resource of resources) {
  const result = readMcpAppResource(resource.uri);
  assert.equal(result.contents[0].mimeType, "text/html;profile=mcp-app");
  assert.deepEqual(result.contents[0]._meta.ui.csp, { connectDomains: [], resourceDomains: [] });
  assert.match(result.contents[0].text, /ui\/initialize/);
  assert.match(result.contents[0].text, /textContent/);
  assert.doesNotMatch(result.contents[0].text, /localStorage|Authorization|Bearer|fetch\(/);
}
assert.throws(() => readMcpAppResource("ui://unknown"));
assert.equal(withMcpAppMetadata({name: "reference_get", inputSchema: {}})._meta?.ui.resourceUri, resources[0].uri);
assert.equal(withMcpAppMetadata({name: "story_get", inputSchema: {}})._meta?.ui.resourceUri, resources[1].uri);
assert.equal(withMcpAppMetadata({name: "reviews_list", inputSchema: {}})._meta, undefined);
console.log("MCP App resource checks passed");

const plain = { content: [{ type: "text", text: "Readable result" }], structuredContent: { reference: { title: "A reference" } } };
const decorated = withMcpAppResult(plain, ["reference_get", "reference_decide"]);
assert.deepEqual(decorated.content, plain.content);
assert.deepEqual(decorated.structuredContent, plain.structuredContent);
assert.deepEqual((decorated as any)._meta.papyrus.availableTools, ["reference_get", "reference_decide"]);
