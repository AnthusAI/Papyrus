import assert from "node:assert/strict";
import fs from "node:fs";
import { editorTypeChoices, typeLabel } from "../lib/newsroom-articles";
import { SYSTEM_ITEM_TYPES, UNTYPED_ITEM_TYPE, isStoryItemType } from "../lib/content-item-lifecycle";
import { describeBase, siteStoryTypes, storyAddress, storyTypesFromProjection, typeForNewStory } from "../lib/site-story-types";
import { projectionTypesEnvironment, projectionTypesSlice } from "../packages/papyrus/src/with-papyrus.mjs";
import path from "node:path";
import os from "node:os";

type Case = { name: string; projection: unknown; expect: { default?: string; types?: string[]; error?: true } };
const cases = JSON.parse(fs.readFileSync(new URL("./fixtures/story-types-cases.json", import.meta.url), "utf8")) as Case[];

// The Python module runs the same cases (procedures/newsroom/tests/test_story_types.py): both languages derive the same default and offered types.
for (const { name, projection, expect } of cases) {
  if (expect.error) {
    assert.throws(() => storyTypesFromProjection(projection), name);
    continue;
  }
  const found = storyTypesFromProjection(projection);
  assert.equal(found.default, expect.default, name);
  assert.deepEqual(found.types, expect.types, name);
}

// One system set per language: the TypeScript list is the Python tuple.
const python = fs.readFileSync(new URL("../src/papyrus_content/content_item_lifecycle.py", import.meta.url), "utf8");
const tuple = /^SYSTEM_ITEM_TYPES = \(([^)]*)\)/m.exec(python)?.[1] ?? "";
assert.deepEqual([...SYSTEM_ITEM_TYPES], [...tuple.matchAll(/"([^"]+)"/g)].map(match => match[1]), "SYSTEM_ITEM_TYPES is the same list in TypeScript and Python");

// Where a Story is published: a declared section wins, then the type's entry, then the root, and otherwise there is no public page.
const routed = storyTypesFromProjection({
  urls: { types: { article: { base: "articles" }, post: { base: "posts" } }, sections: { platform: { base: "platform", aliases: ["Platform"] } } },
  listings: { types: ["article", "post", "guide"] },
});
assert.deepEqual(storyAddress(routed, "post", null), { kind: "route", base: "posts", via: "type" });
assert.deepEqual(storyAddress(routed, "post", "platform"), { kind: "route", base: "platform", via: "section" }, "a declared section decides before the type");
assert.deepEqual(storyAddress(routed, "article", "Platform"), { kind: "route", base: "platform", via: "section" }, "an alias answers to the section");
assert.deepEqual(storyAddress(routed, "guide", null), { kind: "route", base: "", via: "root" }, "a listed type with no section is a page of the root");
assert.equal(storyAddress(routed, "guide", "security").kind, "none", "an undeclared section on a type with no entry has no page");
assert.equal(storyAddress(routed, "case_study", null).kind, "none", "a type the projection does not build has no page");
assert.match((storyAddress(routed, "case_study", null) as { reason: string }).reason, /no page for the type "case_study"/);
assert.equal(storyAddress(storyTypesFromProjection({}), "article", null).kind, "route", "the article type is always projected");
assert.equal(describeBase("posts"), "/posts/");
assert.equal(describeBase(""), "the site root");

// What the editor offers: the site's types, the page, and the Item's own type when it is neither.
assert.deepEqual(editorTypeChoices("article", ["article", "post"]), ["article", "post", "page"]);
assert.deepEqual(editorTypeChoices("legacy", ["article"]), ["article", "page", "legacy"], "a type the site no longer offers stays visible");
assert.equal(typeLabel("case_study"), "Case study");
assert.equal(typeLabel(UNTYPED_ITEM_TYPE), "Not set");
assert.deepEqual(editorTypeChoices(UNTYPED_ITEM_TYPE, ["article"]), ["article", "page"], "an untyped Story is not offered 'untyped' as a choice: it shows as not set");

// A site with no default gives a new Story no type; one with a default gives that. The untyped value is a Story on the board, in the Python mirror too.
assert.equal(typeForNewStory(storyTypesFromProjection({})), "untyped");
assert.equal(typeForNewStory(storyTypesFromProjection({ storyTypes: { default: "post" } })), "post");
assert.equal(isStoryItemType(UNTYPED_ITEM_TYPE), true);
assert.equal(isStoryItemType("newsletter_issue"), true, "newsletter issues are Stories on the board");
const untypedPython = /^UNTYPED_ITEM_TYPE = "([^"]+)"/m.exec(python)?.[1];
assert.equal(untypedPython, UNTYPED_ITEM_TYPE, "the untyped value is the same string in both languages");

// The runtime reads the slice withPapyrus inlines, and has no types and no default with none or with an invalid one.
assert.deepEqual(siteStoryTypes({}).types, []);
assert.equal(siteStoryTypes({}).default, null);
assert.deepEqual(siteStoryTypes({ NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES: JSON.stringify({ storyTypes: { default: "post", types: ["post", "article"] } }) }).types, ["post", "article"]);
const warn = console.warn;
console.warn = () => {};
assert.deepEqual(siteStoryTypes({ NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES: "{\"storyTypes\":{\"default\":\"page\"}}" }).types, []);
console.warn = warn;

// withPapyrus copies only the Story-type settings of the site's projection.json.
const slice = projectionTypesSlice({ site: { name: "x" }, nav: [], urls: { style: "directory", types: { post: { base: "posts", label: "Posts" } }, sections: { a: { base: "a", aliases: ["A"], pages: false } } }, listings: { types: ["post"], pageSize: 9 }, storyTypes: { default: "post" } });
assert.deepEqual(slice, { storyTypes: { default: "post" }, urls: { types: { post: { base: "posts" } }, sections: { a: { base: "a", aliases: ["A"] } } }, listings: { types: ["post"] } });
assert.deepEqual(projectionTypesSlice({ publication: { timeZone: "America/New_York", name: "x" } }).publication, { timeZone: "America/New_York" }, "and the publication's time zone, for scheduling");
const directory = fs.mkdtempSync(path.join(os.tmpdir(), "story-types-"));
assert.deepEqual(projectionTypesEnvironment(directory), {}, "a site with no projection.json sets nothing");
fs.mkdirSync(path.join(directory, "web"));
fs.writeFileSync(path.join(directory, "web", "projection.json"), JSON.stringify({ urls: { types: { guide: {} } } }));
const environment = projectionTypesEnvironment(directory);
assert.deepEqual(storyTypesFromProjection(JSON.parse(environment.NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES)).types, ["guide"]);
fs.rmSync(directory, { recursive: true });

console.log("story types tests passed");
