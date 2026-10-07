import assert from "node:assert/strict";

async function main() {
  const { readInlineExcerpt } = await import("../lib/graphql-content-repository");
  assert.equal(readInlineExcerpt({ excerpt: " Direct " }), "Direct");
  assert.equal(readInlineExcerpt({ customExcerpt: " Custom " }), "Custom");
  assert.equal(readInlineExcerpt({ excerpt: "Direct", customExcerpt: "Custom" }), "Direct");
  assert.equal(readInlineExcerpt({ newsroom: { excerpt: "Nested" } }), "Nested");
  assert.equal(readInlineExcerpt({ newsroom: { customExcerpt: "Nested custom" } }), "Nested custom");
  assert.equal(readInlineExcerpt(JSON.stringify({ customExcerpt: "From JSON" })), "From JSON");
  assert.equal(readInlineExcerpt({ customExcerpt: "  " }), null);
  assert.equal(readInlineExcerpt({}), null);
  assert.equal(readInlineExcerpt(null), null);
  console.log("inline excerpt ok");
}

void main();
