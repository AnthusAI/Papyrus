import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { getNewsroomNavHref, NEWSROOM_OPS_NAV } from "../lib/newsroom-nav";
import { ORGANIZER_NAV_GROUPS, ORGANIZER_SETTINGS_DESTINATION } from "../lib/newsroom-organizer-nav";
import { getContentItemName } from "../lib/site-brand";

const NEWSROOM_APP_DIRECTORY = path.join(__dirname, "..", "app", "newsroom");
const OVERVIEW_SOURCE = readFileSync(path.join(__dirname, "..", "components", "newsroom-ops-overview.tsx"), "utf8");
const SHELL_SOURCE = readFileSync(path.join(__dirname, "..", "components", "newsroom-ops-shell.tsx"), "utf8");

const EXPECTED_SECTION_IDS = [
  "overview",
  "articles",
  "assignments",
  "references",
  "messages",
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
    .filter((entry) => !readFileSync(path.join(NEWSROOM_APP_DIRECTORY, entry.name, "page.tsx"), "utf8").includes("permanentRedirect("))
    .map((entry) => entry.name);
}

function run() {
  assert.deepEqual([...navigationIds()].sort(), [...EXPECTED_SECTION_IDS].sort());

  const articlesEntry = NEWSROOM_OPS_NAV.find((item) => item.id === "articles");
  assert.ok(articlesEntry, "Articles must be in the newsroom navigation");
  assert.ok(articlesEntry.href.endsWith("/articles") || articlesEntry.href === "/articles");
  assert.equal(getNewsroomNavHref("/newsroom/articles", true), "/newsroom/articles?demo=1");
  assert.equal(articlesEntry.label, getContentItemName().plural, "the content item tab uses the publication's configured name");
  const organizerContentItemEntry = ORGANIZER_NAV_GROUPS.flatMap((group) => group.items).find((item) => item.key === "articles");
  assert.equal(organizerContentItemEntry?.label, getContentItemName().plural);

  for (const routeDirectory of staticRouteDirectories()) {
    assert.ok(
      navigationIds().includes(routeDirectory) || ORGANIZER_SETTINGS_DESTINATION.path === `/newsroom/${routeDirectory}` || ORGANIZER_NAV_GROUPS.some(group => group.items.some(item => item.path === `/newsroom/${routeDirectory}`)),
      `app/newsroom/${routeDirectory} has no newsroom navigation entry`,
    );
  }

  assert.match(OVERVIEW_SOURCE, /NEWSROOM_OPS_NAV\.filter/, "landing page destinations must derive from the shared navigation");
  assert.match(SHELL_SOURCE, /ORGANIZER_NAV_GROUPS\.(flatMap|map)/, "shell sidebar must render the organizer navigation");

  console.log("newsroom navigation ok");
}

run();
