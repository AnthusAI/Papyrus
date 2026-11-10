const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = async (name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-newsroom-board-story-types.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
const passed = (world, name) => assert.ok(world.result.includes(`Board story types scenario passed: ${name}`));

Given("a Copywriting column holding a wiki page and an article", function () { this.result = ""; });
Given("published Items that are a wiki page, a doctrine page, a page and an article", function () { this.result = ""; });
Given("forty wiki pages, a doctrine page, three articles in Copywriting and one published article", function () { this.result = ""; });
Given("a stage with 1,362 newer wiki pages ahead of 25 articles", function () { this.result = ""; });
Given("the system type list", function () { this.result = ""; });
Given("Items of the site's own type \"guide\" and of the types wiki page, post, newsletter issue and untyped", function () { this.result = ""; });

When("the Stories board is built", function () {});
When("a column asks for its first page of stories", { timeout: 120_000 }, async function () { this.result = await run("paging"); });
When("the board and its queries need to know what a story is", { timeout: 120_000 }, async function () { this.result = await run("types"); });

// "the Stories board is built" is shared, so each Then runs the script scenario that its Given set up.
Then("the article is a card in Copywriting", { timeout: 120_000 }, async function () { this.result = await run("copywriting"); passed(this, "copywriting"); });
Then("the wiki page is not on the board", function () { passed(this, "copywriting"); });
Then("only the article is in the Published column", { timeout: 120_000 }, async function () { this.result = await run("published"); passed(this, "published"); });
Then("the board counts four records, three in Copywriting and one in Published", { timeout: 120_000 }, async function () { this.result = await run("counts"); passed(this, "counts"); });
Then("all 25 articles load even though the first requests came back with no stories", function () { passed(this, "paging"); });
Then("every row of the stage was read once and the column then ends", function () { passed(this, "paging"); });
Then("a short page that still has a next token is never taken for the end of the column", function () { passed(this, "paging"); });
Then("a stage with no stories at all ends without looping", function () { passed(this, "paging"); });
Then("wiki pages, doctrine and pages are not stories", function () { passed(this, "types"); });
Then("an article, a post, a newsletter issue, a story with no type and any other type are stories, and the query excludes only the system types", function () { passed(this, "types"); });
Then("the guide, the post, the newsletter issue and the untyped story are cards and the wiki page is not", { timeout: 120_000 }, async function () { this.result = await run("new_type"); passed(this, "new_type"); });

Given("a Story written in Copywriting and later published, whose newest version is not in the first page of the Published column", function () { this.result = ""; });
When("the Stories board loads the Copywriting column", { timeout: 120_000 }, async function () { this.result = await run("superseded"); });
Then("the superseded Copywriting version is not loaded and the Story is not a Copywriting card", function () { passed(this, "superseded"); });
Then("the board asks for story types that are not superseded", function () { passed(this, "superseded"); });
