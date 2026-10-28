import assert from "node:assert/strict";
import { loadAllPages } from "../lib/newsroom-all-pages";

type Row = { id: string };
const pages: Record<string, { items: Row[]; nextToken: string | null; hasMore: boolean }> = {
  first: { items: Array.from({ length: 50 }, (_, n) => ({ id: `r${n}` })), nextToken: "b", hasMore: true },
  b: { items: [{ id: "r49" }, ...Array.from({ length: 50 }, (_, n) => ({ id: `r${n + 50}` }))], nextToken: "c", hasMore: true },
  c: { items: [{ id: "r100" }, { id: "r101" }], nextToken: null, hasMore: false },
};

async function main() {
  const asked: (string | null)[] = [];
  const rows = await loadAllPages<Row>(async (token) => { asked.push(token); return pages[token ?? "first"]; });
  assert.deepEqual(asked, [null, "b", "c"], "follows every nextToken to the end");
  assert.equal(rows.length, 102, "keeps rows past the first page, each once");

  const looping = loadAllPages<Row>(async () => ({ items: [], nextToken: "same", hasMore: true }));
  await assert.rejects(looping, /repeated a page/, "a repeated token stops instead of looping");
  console.log("newsroom all-pages: ok");
}

void main();
