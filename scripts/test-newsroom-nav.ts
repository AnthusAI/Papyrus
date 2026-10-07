import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { getNewsroomNavHref, NEWSROOM_OPS_NAV } from "../lib/newsroom-nav";

const NEWSROOM_APP_DIRECTORY = path.join(__dirname, "..", "app", "newsroom");
const OVERVIEW_SOURCE = readFileSync(path.join(__dirname, "..", "components", "newsroom-ops-overview.tsx"), "utf8");
const SHELL_SOURCE = readFileSync(path.join(__dirname, "..", "components", "newsroom-ops-shell.tsx"), "utf8");

const EXPECTED_SECTION_IDS = [
  "overview",
  "articles",
  "assignments",
  "references",
  "messages",
  "insights",
  "topics",
  "concepts",
  "search",
  "administration",
];

function navigationIds(): string[] {
  return NEWSROOM_OPS_NAV.map((item) => item.id);
}

function staticRouteDirectories(): string[] {
  return readdirSync(NEWSROOM_APP_DIRECTORY, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith("["))
    .filter((entry) => existsSync(path.join(NEWSROOM_APP_DIRECTORY, entry.name, "page.tsx")))
    .map((entry) => entry.name);
}

function run() {
  assert.deepEqual([...navigationIds()].sort(), [...EXPECTED_SECTION_IDS].sort());

  const articlesEntry = NEWSROOM_OPS_NAV.find((item) => item.id === "articles");
  assert.ok(articlesEntry, "Articles must be in the newsroom navigation");
  assert.ok(articlesEntry.href.endsWith("/articles") || articlesEntry.href === "/articles");
  assert.equal(getNewsroomNavHref("/newsroom/articles", true), "/newsroom/articles?demo=1");

  for (const routeDirectory of staticRouteDirectories()) {
    assert.ok(
      navigationIds().includes(routeDirectory),
      `app/newsroom/${routeDirectory} has no newsroom navigation entry`,
    );
  }

  assert.match(OVERVIEW_SOURCE, /NEWSROOM_OPS_NAV\.filter/, "landing page destinations must derive from the shared navigation");
  assert.match(SHELL_SOURCE, /NEWSROOM_OPS_NAV\.map/, "shell sidebar must render the shared navigation");

  console.log("newsroom navigation ok");
}

run();
