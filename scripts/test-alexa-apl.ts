/**
 * The alexa plugin's APL documents: device check, feed and story directives, theme, the touch handler and the preview fixtures.
 * Run with no argument for everything, or with one behaviour name (the Gherkin steps do this); each prints `{"behaviour": ...}`.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { RequestEnvelope } from "ask-sdk-model";
import { aplRenderDirective } from "../amplify/plugins/alexa/apl";
import { feedDocument } from "../amplify/plugins/alexa/apl/feed";
import { storyDocument } from "../amplify/plugins/alexa/apl/story";
import { supportsApl } from "../amplify/plugins/alexa/apl/support/device";
import { feedDirective, storyDirective } from "../amplify/plugins/alexa/apl/support/directives";
import { APL_VERSION, VIEWPORT_PROFILES, sizesFor } from "../amplify/plugins/alexa/apl/support/shared";
import { DEFAULT_APL_THEME, themeFromConfig, themeFromTokens } from "../amplify/plugins/alexa/apl/support/theme";
import { contrastRatio, resolveAlexaConfig } from "../amplify/plugins/alexa/config";
import type { PublicStory } from "../amplify/plugins/alexa/contracts";
import { createAplUserEventIntent, aplUserEventIntent } from "../amplify/plugins/alexa/intents/apl-user-event";
import { PILOBOL_US_THEME_PACK_TOKENS } from "../lib/site-stack";
import { PREVIEW_DIRECTORY, previewFixtures, SAMPLE_STORIES } from "./alexa/render-apl-previews";

const request = { name: "alexa", invocationName: "the example" };

function envelope(supportedInterfaces: Record<string, unknown>, requestPart: Record<string, unknown> = { type: "LaunchRequest" }): RequestEnvelope {
  return {
    version: "1.0",
    session: { new: false, sessionId: "s", application: { applicationId: "a" }, user: { userId: "u" } },
    context: { System: { application: { applicationId: "a" }, user: { userId: "u" }, device: { deviceId: "d", supportedInterfaces }, apiEndpoint: "https://api.amazonalexa.com" } },
    request: { requestId: "r", timestamp: "2026-10-31T00:00:00Z", locale: "en-US", ...requestPart },
  } as unknown as RequestEnvelope;
}

const story: PublicStory & { imageUrl?: string } = { id: "a", slug: "first", title: "Title", byline: "Sample Writer", publishedAt: "2026-10-30T12:00:00Z", markus: "" };

/** Collects every string in a JSON value. */
function strings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(strings);
  if (typeof value === "object" && value !== null) return Object.values(value).flatMap(strings);
  return [];
}

function fakeHandlerInput(requestEnvelope: RequestEnvelope) {
  const spoken: string[] = [];
  const builder: any = {
    speak: (text: string) => (spoken.push(text), builder),
    withShouldEndSession: () => builder,
    getResponse: () => ({ outputSpeech: { ssml: spoken[spoken.length - 1] } }),
  };
  return { handlerInput: { requestEnvelope, responseBuilder: builder } as any, spoken };
}

const behaviours: Record<string, () => Promise<void> | void> = {
  "an APL device gets a directive and a voice-only device gets none": () => {
    assert.equal(supportsApl(envelope({ "Alexa.Presentation.APL": { runtime: { maxVersion: "2023.3" } } })), true);
    assert.equal(supportsApl(envelope({ AudioPlayer: {} })), false);
    assert.equal(supportsApl(envelope({})), false);
    const noDevice = envelope({});
    delete (noDevice.context.System as { device?: unknown }).device;
    assert.equal(supportsApl(noDevice), false);
  },

  "the feed directive carries the stories as a datasource": () => {
    const directive = feedDirective([{ ...SAMPLE_STORIES[0] }, SAMPLE_STORIES[1]], DEFAULT_APL_THEME, "Pilobolus");
    assert.equal(directive.type, "Alexa.Presentation.APL.RenderDocument");
    assert.equal(directive.token, "feed");
    assert.deepEqual(directive.document, feedDocument.document);
    const data = directive.datasources.feedData as any;
    assert.equal(data.publication, "Pilobolus");
    assert.deepEqual(data.theme, DEFAULT_APL_THEME);
    assert.deepEqual(data.stories.map((entry: { index: number }) => entry.index), [0, 1]);
    assert.equal(data.stories[0].title, SAMPLE_STORIES[0].title);
    assert.equal(data.stories[0].imageUrl, SAMPLE_STORIES[0].imageUrl);
    assert.equal("imageUrl" in data.stories[1], false, "a story without an image has no image key");
    assert.equal(data.stories[1].deck, SAMPLE_STORIES[1].deck);
    assert.deepEqual(directive, { ...aplRenderDirective("feed", directive.datasources) });
  },

  "the story directive carries the title, byline, date and body": () => {
    const directive = storyDirective({ ...story, imageUrl: "https://example.com/x.jpg" }, ["One.", "Two."], DEFAULT_APL_THEME);
    assert.equal(directive.token, "story");
    assert.deepEqual(directive.document, storyDocument.document);
    const data = directive.datasources.storyData as any;
    assert.equal(data.title, "Title");
    assert.equal(data.meta, "Sample Writer · October 30, 2026");
    assert.equal(data.imageUrl, "https://example.com/x.jpg");
    assert.deepEqual(data.paragraphs, ["One.", "Two."]);
    const bare = storyDirective({ ...story, byline: undefined, publishedAt: "not a date" }, [], DEFAULT_APL_THEME).datasources.storyData as any;
    assert.equal(bare.meta, "");
    assert.equal("imageUrl" in bare, false);
  },

  "a touched card opens the story at its index": async () => {
    const opened: number[] = [];
    const touchModule = createAplUserEventIntent({ openStory: (_input, index) => (opened.push(index), { outputSpeech: { type: "PlainText", text: "opened" } }) });
    const handler = touchModule.create({} as never);
    const event = (args: unknown[]) => envelope({ "Alexa.Presentation.APL": {} }, { type: "Alexa.Presentation.APL.UserEvent", arguments: args, source: {} });
    const { handlerInput } = fakeHandlerInput(event(["openStory", 2]));
    assert.equal(await handler.canHandle(handlerInput), true);
    await handler.handle(handlerInput);
    await handler.handle(fakeHandlerInput(event(["openStory", "1"])).handlerInput);
    assert.deepEqual(opened, [2, 1]);
    assert.equal(await handler.canHandle(fakeHandlerInput(envelope({}, { type: "LaunchRequest" })).handlerInput), false);
    // A malformed event never reaches openStory.
    const bad = fakeHandlerInput(event(["openStory", -1]));
    await handler.handle(bad.handlerInput);
    assert.deepEqual(opened, [2, 1]);
    assert.match(bad.spoken[0], /could not tell/);
    // The default opener is speech only.
    const stub = fakeHandlerInput(event(["openStory", 0]));
    await aplUserEventIntent.create({} as never).handle(stub.handlerInput);
    assert.match(stub.spoken[0], /Opening story 1/);
    assert.equal(touchModule.interactionModel, undefined);
  },

  "each document is valid APL laid out for every viewport profile": () => {
    for (const { id, document } of [feedDocument, storyDocument]) {
      assert.equal(document.type, "APL", id);
      const [year, minor] = String(document.version).split(".").map(Number);
      const [minimumYear, minimumMinor] = APL_VERSION.split(".").map(Number);
      assert.ok(year > minimumYear || (year === minimumYear && minor >= minimumMinor), `${id} is APL ${APL_VERSION} or newer`);
      assert.deepEqual(document.import, [{ name: "alexa-viewport-profiles", version: "1.6.0" }]);
      const text = JSON.stringify(document);
      // Every profile has its own sizes, and every @resource the layout uses is defined.
      for (const profile of VIEWPORT_PROFILES) {
        assert.ok(text.includes(`\${@viewportProfile == @${profile}}`), `${id} has sizes for ${profile}`);
      }
      const defined = new Set((document.resources as { dimensions?: Record<string, number> }[]).flatMap((block) => Object.keys(block.dimensions ?? {})));
      const used = new Set([...text.matchAll(/"@([a-zA-Z]+)"/g)].map((match) => match[1]));
      for (const name of used) assert.ok(defined.has(name), `${id} uses @${name}, which resources define`);
      const conditions = strings(document).filter((value) => value.includes("@viewportProfile"));
      for (const condition of conditions) {
        const referenced = [...condition.matchAll(/@(hub\w+|tv\w+)/g)].map((match) => match[1]);
        for (const name of referenced) assert.ok((VIEWPORT_PROFILES as readonly string[]).includes(name), `${id} refers to a known profile (${name})`);
      }
      // No borders or hairlines: flat fills and rounded corners only.
      assert.ok(!/border(Width|Color|Strokes)|"borderWidth"/.test(text), `${id} has no borders`);
      assert.ok(!text.includes("AlexaDivider") && !text.includes("Divider"), `${id} has no dividers`);
    }
    // Readable: body and deck sizes never shrink below the guidance floor, and TVs are larger than hubs.
    for (const profile of VIEWPORT_PROFILES) {
      const sizes = sizesFor(profile);
      assert.ok(sizes.metaSize >= 18 && sizes.deckSize >= 20 && sizes.bodySize >= 22 && sizes.headlineSize >= 26, `${profile} text is readable`);
    }
    assert.ok(sizesFor("tvLandscapeXLarge").bodySize >= 30);
    // The feed touch sends the story index; the story has a scrolling body.
    assert.ok(JSON.stringify(feedDocument.document).includes('"arguments":["openStory","${index}"]'));
    assert.ok(JSON.stringify(storyDocument.document).includes('"ScrollView"'));
  },

  "the theme comes from the site config with a brand fallback": () => {
    assert.deepEqual(themeFromConfig(resolveAlexaConfig(request)), DEFAULT_APL_THEME);
    const custom = { background: "#000000", surface: "#111111", text: "#ffffff", mutedText: "#cccccc", accent: "#ffcc00" };
    assert.deepEqual(themeFromConfig(resolveAlexaConfig({ ...request, theme: custom })), custom);
    assert.deepEqual(resolveAlexaConfig({ ...request, theme: { ...custom, text: "#FFFFFF" } }).theme, custom, "colours are lowercased");
    const dark = themeFromTokens(PILOBOL_US_THEME_PACK_TOKENS, "dark");
    assert.deepEqual(dark, { background: "#14170f", surface: "#1c2117", text: "#dfded0", mutedText: "#8b9184", accent: "#b7d18a" });
    assert.deepEqual(dark, DEFAULT_APL_THEME);
    assert.equal(themeFromTokens(PILOBOL_US_THEME_PACK_TOKENS, "light").background, "#f1ead9");
    for (const theme of [dark, themeFromTokens(PILOBOL_US_THEME_PACK_TOKENS, "light")]) {
      for (const ground of [theme.background, theme.surface]) {
        assert.ok(contrastRatio(theme.text, ground) >= 4.5 && contrastRatio(theme.mutedText, ground) >= 4.5);
      }
    }
    assert.throws(() => resolveAlexaConfig({ ...request, theme: { ...custom, extra: "#000000" } }), /unknown colours: extra/);
    assert.throws(() => resolveAlexaConfig({ ...request, theme: { ...custom, accent: "gold" } }), /accent must be a colour/);
    assert.throws(() => resolveAlexaConfig({ ...request, theme: { ...custom, mutedText: "#222222" } }), /contrast ratio/);
    assert.throws(() => resolveAlexaConfig({ ...request, theme: "dark" }), /must be an object/);
  },

  "preview fixtures exist for every document and profile": () => {
    const fixtures = previewFixtures();
    assert.equal(Object.keys(fixtures).length, 2 * VIEWPORT_PROFILES.length);
    for (const [name, content] of Object.entries(fixtures)) {
      assert.equal(readFileSync(path.join(PREVIEW_DIRECTORY, name), "utf8"), content, `${name} is up to date: run npx tsx scripts/alexa/render-apl-previews.ts`);
      assert.equal(JSON.parse(content).document.type, "APL");
    }
  },
};

async function main() {
  const requested = process.argv[2];
  const names = requested === undefined ? Object.keys(behaviours) : [requested];
  for (const name of names) {
    const behaviour = behaviours[name];
    assert.ok(behaviour, `unknown behaviour "${name}"`);
    await behaviour();
    console.log(JSON.stringify({ behaviour: name }));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
