import assert from "node:assert/strict";
import test from "node:test";
import { SITE_DOCUMENT, documentFromFiles, filesFromDocument } from "./fixtures/writing-guidelines-fixture";
import {
  addableFieldFiles, bulletsOf, dumpFrontMatter, exemplarsBody, exemplarsOf, fileText, foldersOf, lockedInFiles, newRuleFile, newRuleName, parseFrontMatter, restoreFolder, ruleFileChanges, severityOf,
  stateOf, withBody, withMeta, withoutFolder,
} from "../lib/guidelines/guideline-files";
import { derivedChecks, describeChange, diffDocuments, isLocked, matchStories, reasonProblem, sourceWords, writingSlug } from "../lib/guidelines/writing-guidelines-admin";

test("front matter is written the way the file form writes it, and read back the same", () => {
  const meta = { id: "urn:uuid:1", type: "papyrus:Guideline", name: "plain-claims", description: 'Say "plain" things.', kind: "writing", scope: "publication", severity: "warn", avoid: ["a", "b c"], maxLength: 900 };
  assert.equal(dumpFrontMatter(meta), 'id: "urn:uuid:1"\ntype: "papyrus:Guideline"\nname: "plain-claims"\ndescription: "Say \\"plain\\" things."\nkind: "writing"\nscope: "publication"\nseverity: "warn"\navoid: ["a", "b c"]\nmaxLength: 900\n');
  assert.deepEqual(parseFrontMatter(dumpFrontMatter(meta)), meta);
});

test("the front matter a person or PyYAML wrote is read: plain and quoted text, block lists, comments", () => {
  const meta = parseFrontMatter("id: https://example.org/id/1\nname: 'it''s'\navoid:\n  - one\n  - \"two\"\nmaxLength: 5 # chars\nlanguage: ~\nok: true\n");
  assert.deepEqual(meta, { id: "https://example.org/id/1", name: "it's", avoid: ["one", "two"], maxLength: 5, language: null, ok: true });
  assert.throws(() => parseFrontMatter("nested:\n  key: value\n"), /not 'key: value'/);
  assert.throws(() => parseFrontMatter("a: 1\na: 2\n"), /twice/);
});

test("a set is read as folders: field files by their fixed name, rule files by any other, supporting files kept", () => {
  const files = { ...filesFromDocument(SITE_DOCUMENT, null, ["plain-claims", "source-first"]), "plain-claims/examples/before.md": "Before.\n", "stray-note.md": "ignored" };
  const found = foldersOf(files);
  assert.equal(found.find((item) => item.folder === "tone")!.role, "field");
  const rule = found.find((item) => item.folder === "plain-claims")!;
  assert.equal(rule.role, "rule"); assert.equal(severityOf(rule), "warn"); assert.deepEqual(rule.extras, ["plain-claims/examples/before.md"]); assert.equal(rule.unreadable, null);
  assert.equal(found.some((item) => item.folder === "stray-note.md"), false);
  assert.deepEqual(documentFromFiles(files).tone, SITE_DOCUMENT.tone, "the document view reads back from the field files");
});

test("an edit keeps the other bytes: a changed key or body rewrites only that file, in key order", () => {
  const files = filesFromDocument(SITE_DOCUMENT, null, ["plain-claims"]);
  const rule = foldersOf(files).find((item) => item.folder === "plain-claims")!;
  assert.equal(withMeta(rule, {}), rule.text, "nothing edited gives the same text");
  const edited = withMeta(rule, { severity: "error", maxLength: 80, avoid: [] });
  assert.match(edited, /severity: "error"\npattern: \["\\\\bvery unique\\\\b"\]\nmaxLength: 80\n---\n/, "an emptied list is dropped and a new key goes where the file form puts it");
  assert.equal(edited.includes("avoid:"), false);
  const again = foldersOf({ "plain-claims/GUIDELINE.md": edited })[0];
  assert.equal(withBody(again, again.body), edited);
  assert.equal(withBody(again, "New prose.\n").endsWith("---\nNew prose.\n"), true);
});

test("a file that does not open with front matter is unreadable here and its text is kept as it is", () => {
  const item = foldersOf({ "odd/GUIDELINE.md": "no front matter" })[0];
  assert.match(item.unreadable ?? "", /front matter block/);
  assert.equal(withBody(item, "x"), "no front matter");
});

test("what changed since the saved set is told per folder: added, changed, removed, unchanged", () => {
  const saved = filesFromDocument(SITE_DOCUMENT, null, ["plain-claims", "source-first"]);
  const draft = { ...withoutFolder(saved, "source-first"), "plain-claims/GUIDELINE.md": saved["plain-claims/GUIDELINE.md"] + "x", "new-rule/GUIDELINE.md": newRuleFile("new-rule", null) };
  assert.equal(stateOf("tone", saved, draft), "unchanged");
  assert.equal(stateOf("plain-claims", saved, draft), "changed");
  assert.equal(stateOf("source-first", saved, draft), "removed");
  assert.equal(stateOf("new-rule", saved, draft), "added");
  assert.deepEqual(ruleFileChanges(saved, draft), [{ folder: "new-rule", change: "added" }, { folder: "plain-claims", change: "changed" }, { folder: "source-first", change: "removed" }]);
  const rejected = restoreFolder(restoreFolder(restoreFolder(draft, saved, "source-first"), saved, "plain-claims"), saved, "new-rule");
  assert.deepEqual(rejected, saved, "rejecting each file puts the saved set back");
});

test("a new rule file is guidance with a permanent id, and its name is checked in words", () => {
  const text = newRuleFile("no-filler", "AI Desk");
  const [rule] = foldersOf({ "no-filler/GUIDELINE.md": text });
  assert.equal(severityOf(rule), "guidance"); assert.equal(rule.meta.scope, "section/ai-desk"); assert.equal(rule.meta.kind, "writing");
  assert.match(String(rule.meta.id), /^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(newRuleName("no-filler", ["tone"]), null);
  assert.match(newRuleName("No Filler", []) ?? "", /lowercase words joined by hyphens/);
  assert.match(newRuleName("tone", []) ?? "", /name of a field file/);
  assert.match(newRuleName("plain-claims", ["plain-claims"]) ?? "", /already a file/);
  assert.match(newRuleName(" ", []) ?? "", /Give the rule a name/);
});

test("a section is offered only the field files it may add: no site-only file and none the site locks", () => {
  const offered = (section: string | null, locked: string[] = []) => addableFieldFiles(new Set(["tone"]), section, locked).map((item) => item.name);
  assert.ok(offered(null).includes("locked") && offered(null).includes("constraints"));
  assert.equal(offered(null).includes("tone"), false, "a file already there is not offered again");
  assert.equal(offered(null).includes("register"), false, "register is a language overlay's field");
  assert.equal(offered("ai").includes("locked") || offered("ai").includes("constraints") || offered("ai").includes("judge"), false);
  assert.equal(offered("ai", ["audience"]).includes("audience"), false);
  assert.ok(offered("ai", ["audience"]).includes("voice"));
});

test("the fields the site locks are read from its locked file", () => {
  assert.deepEqual(lockedInFiles(filesFromDocument(SITE_DOCUMENT)), ["audience"]);
  assert.deepEqual(bulletsOf("- a\n  more\n- b\n"), ["a", "b"]);
  assert.deepEqual(lockedInFiles({}), []);
});

test("the voice examples of an exemplars file are read and written as its fenced list", () => {
  const body = exemplarsBody([{ storyLineageId: "s1", note: "Plain." }, { storyLineageId: "s2" }]);
  assert.deepEqual(exemplarsOf(body), [{ storyLineageId: "s1", note: "Plain." }, { storyLineageId: "s2" }]);
  assert.equal(exemplarsOf("not a list"), null);
  assert.equal(fileText({ a: "b" }, "x\n"), '---\na: "b"\n---\nx\n');
});

test("a reason is required and blank spaces are not one", () => {
  assert.match(reasonProblem("  ") ?? "", /Say why/);
  assert.equal(reasonProblem("Because"), null);
});

test("each field says where it came from in words, and a locked field says so", () => {
  const sources = { tone: [{ layer: "publication" }, { layer: "section" }], voice: [{ layer: "publication" }], editorialAim: [{ layer: "section" }] } as any;
  assert.equal(sourceWords("tone", sources, SITE_DOCUMENT, true), "Site and this section");
  assert.equal(sourceWords("voice", sources, SITE_DOCUMENT, true), "Site");
  assert.equal(sourceWords("editorialAim", sources, SITE_DOCUMENT, true), "This section");
  assert.equal(sourceWords("audience", sources, SITE_DOCUMENT, true), "Locked by site");
  assert.equal(sourceWords("audience", sources, SITE_DOCUMENT, false), "Site");
  assert.equal(isLocked(SITE_DOCUMENT, "audience"), true);
});

test("changes between two versions are described in plain words", () => {
  const changes = diffDocuments({ schemaVersion: 2, tone: ["a"], audience: "x" }, { schemaVersion: 2, tone: ["b"], bodyMarkus: "Lead." });
  assert.deepEqual(changes.map((change) => change.path), ["audience", "bodyMarkus", "tone"]);
  assert.deepEqual(changes.map(describeChange), ['Audience: removed "x"', 'Guidance in your own words: added "Lead."', 'Tone: changed from ["a"] to ["b"]']);
});

test("derived checks are the ones whose source names this document, never a hand-written one", () => {
  const policies = [
    { source: "writing-guidelines:editorial-doctrine-writing:v3" }, { source: "writing-guidelines:desk-doctrine-ai-writing:v1" }, { source: "custom" }, { source: "starter:x" },
  ];
  assert.equal(derivedChecks(policies, null).length, 1);
  assert.equal(derivedChecks(policies, "AI").length, 1);
  assert.equal(writingSlug("Culture & Arts"), "desk-doctrine-culture-arts-writing");
});

test("the Story picker narrows by title", () => {
  const stories = [{ lineageId: "a", title: "A good headline" }, { lineageId: "b", title: "Agent mistakes" }];
  assert.deepEqual(matchStories(stories, "HEADLINE").map((story) => story.lineageId), ["a"]);
});
