const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const { spawnSync } = require("node:child_process");
const { Given, When, Then } = require("@cucumber/cucumber");

function registerTypeScriptRequire() {
  if (require.extensions[".ts"]) return;
  require.extensions[".ts"] = (module, filename) => {
    const source = fs.readFileSync(filename, "utf8");
    const output = ts.transpileModule(source, {
      compilerOptions: {
        esModuleInterop: true,
        module: ts.ModuleKind.CommonJS,
        moduleResolution: ts.ModuleResolutionKind.Node10,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: filename,
    });
    module._compile(output.outputText, filename);
  };
}

function loadItemStream() {
  registerTypeScriptRequire();
  return require("../../lib/item-stream.ts");
}

function runProbe(args) {
  const result = spawnSync("npx", ["tsx", "scripts/probe-editions-optional.ts", ...args], {
    cwd: path.resolve(__dirname, "../.."),
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

const EDITION_ROUTE_SOURCES = [
  "app/[year]/[month]/[day]/page.tsx",
  "app/[year]/[month]/[day]/[articleSlug]/page.tsx",
  "app/[year]/[month]/[day]/page/[pageNumber]/page.tsx",
  "app/[year]/[month]/[day]/section/[sectionKey]/page.tsx",
  "app/archive/page.tsx",
  "app/api/archive/editions/route.ts",
];

function articleItem(slug, section) {
  return {
    type: "article",
    slug,
    section,
    headline: slug,
    deck: "",
    byline: "Staff",
    dateline: "",
    body: ["Body."],
  };
}

const STREAM_ARTICLES_BY_SLUG = {
  "newer-story": articleItem("newer-story", "Security"),
  "older-story": articleItem("older-story", "Culture"),
  "older-security-story": articleItem("older-security-story", "Security"),
  "standalone-story": articleItem("standalone-story", "Satire"),
};

Given("a brand without an editions setting", function () {
  this.brand = { id: "plain" };
});

Given("a brand with editions enabled", function () {
  this.brand = { id: "dated", editions: { enabled: true } };
});

Then("editions are disabled", function () {
  assert.equal(runProbe(["setting", JSON.stringify(this.brand)]).editionsEnabled, false);
});

Then("a brand with editions enabled has editions enabled", function () {
  assert.equal(runProbe(["setting", JSON.stringify({ id: "x", editions: { enabled: true } })]).editionsEnabled, true);
});

Then("a brand with editions explicitly disabled has editions disabled", function () {
  assert.equal(runProbe(["setting", JSON.stringify({ id: "x", editions: { enabled: false } })]).editionsEnabled, false);
});

Given("published articles {string} and {string}, newest first", function (first, second) {
  // "older-security-story" keeps the section scenarios meaningful: two sections, one of them filtered.
  this.articles = [STREAM_ARTICLES_BY_SLUG[first], STREAM_ARTICLES_BY_SLUG[second], STREAM_ARTICLES_BY_SLUG["older-security-story"]];
});

Given("a published article {string} and no editions at all", function (slug) {
  this.articles = [STREAM_ARTICLES_BY_SLUG[slug]];
});

Given("no published articles", function () {
  this.articles = [];
});

When("the item stream is built for the home page", function () {
  const { buildItemStream, articlesToStreamItems } = loadItemStream();
  this.streamItems = articlesToStreamItems(this.articles);
  this.stream = buildItemStream(this.streamItems);
});

When("the item stream is built for the section {string}", function (sectionLabel) {
  const { buildItemStream, articlesToStreamItems } = loadItemStream();
  this.streamItems = articlesToStreamItems(this.articles);
  this.stream = buildItemStream(this.streamItems, sectionLabel);
});

Then("the home page loads its stream from the newest published articles and never lists editions", function () {
  const source = fs.readFileSync(path.resolve(__dirname, "../../app/page.tsx"), "utf8");
  const start = source.indexOf("async function loadNewestStreamItems()");
  assert.ok(start >= 0);
  const body = source.slice(start, source.indexOf("async function loadLatestGraphQLEdition"));
  assert.ok(body.includes("listCachedNewestArticles"));
  assert.ok(!body.includes("listCachedPublishedEditions"));
  assert.ok(!body.includes("loadCachedEditionContent"));
});

Then("the first stream item is {string}", function (slug) {
  assert.equal(this.stream.items[0].slug, slug);
});

Then("the stream has no edition date in it", function () {
  assert.equal(Object.prototype.hasOwnProperty.call(this.stream, "editionDate"), false);
});

Then("every stream item is in the section {string}", function (sectionLabel) {
  assert.ok(this.stream.items.length > 0);
  for (const item of this.stream.items) assert.equal(item.section, sectionLabel);
});

Then("the stream still offers the sections {string} and {string}", function (first, second) {
  const labels = this.stream.sections.map((section) => section.label);
  assert.ok(labels.includes(first));
  assert.ok(labels.includes(second));
});

Then("the stream shows every item", function () {
  assert.equal(this.stream.items.length, this.streamItems.length);
  assert.equal(this.stream.activeSectionKey, null);
});

Then("the stream is empty", function () {
  assert.equal(this.stream.items.length, 0);
});

Then("the item stream view says {string}", function (message) {
  const source = fs.readFileSync(path.resolve(__dirname, "../../components/item-stream-view.tsx"), "utf8");
  assert.ok(source.includes(`<p>${message}</p>`));
  assert.ok(source.includes("stream.items.length === 0"));
});

Then(
  "the edition date, edition item, edition page, edition section, archive and archive API routes all answer not found when editions are off",
  function () {
    for (const relativePath of EDITION_ROUTE_SOURCES) {
      const source = fs.readFileSync(path.resolve(__dirname, "../..", relativePath), "utf8");
      const handlerStart = source.search(/export default async function|export async function GET/);
      const guardIndex = source.indexOf("if (!editionsEnabled())");
      assert.ok(handlerStart >= 0 && guardIndex > handlerStart, `${relativePath} guards on editionsEnabled() inside the handler`);
      assert.ok(!/await /.test(source.slice(handlerStart, guardIndex)), `${relativePath} guards before any await`);
    }
  },
);

Then("no edition date routes are enumerated for the build", function () {
  const result = runProbe(["enumeration"]);
  assert.equal(result.editionsEnabled, false);
  assert.deepEqual(result.dateParams, []);
  assert.deepEqual(result.itemParams, []);
});

Then("the edition path for {string} is {string}", function (editionDate, expected) {
  assert.equal(runProbe(["path", editionDate]).path, expected);
});
