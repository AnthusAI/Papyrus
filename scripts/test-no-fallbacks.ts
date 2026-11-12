import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const root = join(__dirname, "..");
const read = (file: string) => readFileSync(join(root, file), "utf8");

test("console chat client: no schema probing", () => {
  const chat = read("lib/console-chat-client.ts");
  assert.doesNotMatch(chat, /__type|__schema|introspection/i);
  assert.doesNotMatch(chat, /_LEGACY\b/);
  assert.doesNotMatch(chat, /schemaFields|SchemaSnapshot|SELECTION_CANDIDATES|isUnavailableQueryError/);
  assert.doesNotMatch(chat, /typeof \w+\.(onCreate|onUpdate)\s*[!=]==\s*"function"/);
});

test("console chat client: one credential", () => {
  const chat = read("lib/console-chat-client.ts");
  assert.doesNotMatch(chat, /apiKey|API_KEY/);
  assert.doesNotMatch(chat, /catch \((first|second)Error\)/);
});

test("console chat client: failures are raised", () => {
  const chat = read("lib/console-chat-client.ts");
  assert.doesNotMatch(chat, /deriveConsoleThreadsFromMessages/);
  assert.doesNotMatch(chat, /hasExplicitThreadIds/);
  assert.doesNotMatch(chat, /allowPartialData/);
  assert.doesNotMatch(chat, /Fall back to/i);
});
