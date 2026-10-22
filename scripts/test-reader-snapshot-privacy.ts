import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";

const SITE_SUBJECT = /ss(?:1|dev)_[A-Za-z0-9_-]{8,}/g;
const EMAIL = /[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]*[A-Za-z][A-Za-z0-9-]*\.)+[A-Za-z]{2,}/g;
const UUID = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g;
const PERSON_ID = /person[-_ ]?id|\bperson[-_][A-Za-z0-9-]{6,}|\bprs_[A-Za-z0-9]+/gi;

function uuidFor(number: number): string {
  const hex = number.toString(16).padStart(32, "0");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
}

function identityLeaks(text: string, allowedReaderIds: string[]): string[] {
  const allowed = new Set(allowedReaderIds.map((id) => id.toLowerCase()));
  const leaks = [SITE_SUBJECT, EMAIL, PERSON_ID].flatMap((pattern) => [...text.matchAll(pattern)].map((match) => match[0]));
  return [...leaks, ...[...text.matchAll(UUID)].map((match) => match[0]).filter((uuid) => !allowed.has(uuid.toLowerCase()))];
}

assert.deepEqual(identityLeaks("ss1_" + "A".repeat(43), []).length, 1);
assert.deepEqual(identityLeaks("reader@example.test", []), ["reader@example.test"]);
assert.deepEqual(identityLeaks(uuidFor(9), []).length, 1);
assert.deepEqual(identityLeaks('{"personId":"x"}', []).length, 1);
assert.deepEqual(identityLeaks("/_plugins/papyrus-reader@1.js", []), []);
assert.deepEqual(identityLeaks(uuidFor(1), [uuidFor(1)]), []);

const fixture = path.join(process.cwd(), "procedures", "newsroom", "tests", "reader_snapshot_fixture.py");
const output = execFileSync(process.env.PAPYRUS_PYTHON ?? "python3", [fixture], { encoding: "utf8" });
const { readerIds, files } = JSON.parse(output) as { readerIds: string[]; files: Record<string, string> };

assert.deepEqual(Object.keys(files).sort(), ["_data/reader/board.json", "_data/reader/comments/item-one.json", "_data/reader/items.json", "_data/reader/readers.json", "_data/reader/submissions.json"]);
for (const [name, body] of Object.entries(files)) {
  assert.deepEqual(identityLeaks(body, readerIds), [], `${name} identifies no one`);
  JSON.parse(body);
}
const readers = (JSON.parse(files["_data/reader/readers.json"]) as { readers: Array<Record<string, unknown>> }).readers;
assert.ok(readers.length > 0, "the fixture has a reader on the karma board");
for (const row of readers) assert.deepEqual(Object.keys(row).sort(), ["handle", "karma", "readerId"], "only readerId, handle and karma are public");
const submissions = (JSON.parse(files["_data/reader/submissions.json"]) as { submissions: Array<Record<string, unknown>> }).submissions;
assert.equal(submissions.length, 1);
assert.deepEqual(Object.keys(submissions[0]).sort(), ["createdAt", "domain", "handle", "id", "kind", "note", "readerId", "similar", "state", "title", "url"], "a submission is public as these fields only: no signals, extraction state, siteSubject or email");
const thread = (JSON.parse(files["_data/reader/comments/item-one.json"]) as { comments: Array<Record<string, unknown>> }).comments;
assert.equal(thread.length, 1);
assert.deepEqual(Object.keys(thread[0]).sort(), ["body", "createdAt", "edited", "handle", "id", "parent", "readerId"], "a comment is public as these fields only: no rating context, signals, siteSubject or email");
for (const body of Object.values(files)) {
  assert.equal(body.includes("siteSubject") || body.includes("email") || body.includes("personId") || body.includes("signals") || body.includes("extractionState") || body.includes("ratingContext"), false, "profile fields other than readerId, handle and karma never reach the files");
}

console.log("reader snapshot privacy ok");
