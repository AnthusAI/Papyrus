/**
 * Renders each APL document for each viewport profile as a JSON fixture for the APL authoring tool (developer.amazon.com/alexa/console/ask,
 * "Display" -> "Import"): `document` and `datasources` paste into the two editors, `viewport` says which device to pick.
 *   npx tsx scripts/alexa/render-apl-previews.ts
 * scripts/test-alexa-apl.ts fails when the committed fixtures differ from what this renders.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { PublicStory } from "../../amplify/plugins/alexa/contracts";
import { feedDirective, storyDirective } from "../../amplify/plugins/alexa/apl/support/directives";
import { VIEWPORT_PROFILES, type ViewportProfile } from "../../amplify/plugins/alexa/apl/support/shared";
import { DEFAULT_APL_THEME } from "../../amplify/plugins/alexa/apl/support/theme";

/** The nominal viewport of each profile in dp, as the authoring tool's device list names them. */
export const PROFILE_VIEWPORTS: Record<ViewportProfile, { device: string; width: number; height: number; dpi: number; shape: "ROUND" | "RECTANGLE" }> = {
  hubRoundSmall: { device: "Echo Spot", width: 480, height: 480, dpi: 160, shape: "ROUND" },
  hubLandscapeSmall: { device: "Echo Show 5", width: 960, height: 480, dpi: 160, shape: "RECTANGLE" },
  hubLandscapeMedium: { device: "Echo Show 8", width: 960, height: 600, dpi: 213, shape: "RECTANGLE" },
  hubLandscapeLarge: { device: "Echo Show 10", width: 1280, height: 800, dpi: 160, shape: "RECTANGLE" },
  tvLandscapeXLarge: { device: "Fire TV", width: 960, height: 540, dpi: 160, shape: "RECTANGLE" },
};

const LONG = "A fungus that shoots its spores at a target and a newsroom that reads what it finds. ";
export const SAMPLE_STORIES = [
  { id: "a", slug: "first", title: "The spores that outrun the wind", deck: "A tiny fungus fires its cargo faster than a rifle bullet.", byline: "Sample Writer", publishedAt: "2026-10-30T12:00:00Z", imageUrl: "https://example.com/first.jpg" },
  { id: "b", slug: "second", title: "A story with no picture and a rather long headline that has to wrap onto a few lines", deck: "A deck that is also long enough to need more than one line on the smallest screens in the family.", publishedAt: "2026-10-29T12:00:00Z" },
  { id: "c", slug: "third", title: "Short one", publishedAt: "2026-10-28T12:00:00Z", imageUrl: "https://example.com/third.jpg" },
];
const SAMPLE_STORY: PublicStory & { imageUrl: string } = { ...SAMPLE_STORIES[0], markus: "", imageUrl: "https://example.com/first.jpg" };
const PARAGRAPHS = Array.from({ length: 8 }, (_, index) => `${LONG.repeat(3)}(${index + 1})`);

export function previewFixtures(): Record<string, string> {
  const fixtures: Record<string, string> = {};
  for (const profile of VIEWPORT_PROFILES) {
    const viewport = { profile, ...PROFILE_VIEWPORTS[profile] };
    const feed = feedDirective(SAMPLE_STORIES, DEFAULT_APL_THEME, "Pilobolus");
    const story = storyDirective(SAMPLE_STORY, PARAGRAPHS, DEFAULT_APL_THEME);
    for (const [name, directive] of [["feed", feed], ["story", story]] as const) {
      const { document, datasources } = directive;
      fixtures[`${name}-${profile}.json`] = `${JSON.stringify({ viewport, document, datasources }, null, 2)}\n`;
    }
  }
  return fixtures;
}

export const PREVIEW_DIRECTORY = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/alexa-apl-previews");

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  mkdirSync(PREVIEW_DIRECTORY, { recursive: true });
  for (const [name, content] of Object.entries(previewFixtures())) writeFileSync(path.join(PREVIEW_DIRECTORY, name), content);
  console.log(`Wrote ${Object.keys(previewFixtures()).length} fixtures to ${PREVIEW_DIRECTORY}`);
}
