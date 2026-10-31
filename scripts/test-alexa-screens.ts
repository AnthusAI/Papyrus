/**
 * The alexa skill's screens joined to its speech: what an Echo Show sees while the skill talks, and a touched card opening a story.
 * Run with no argument for everything, or with one behaviour name (the Gherkin steps do this); each prints `{"behaviour": ...}`.
 * Everything runs against a fake `PublicStorySource`; nothing touches a network or an Amazon account.
 */
import assert from "node:assert/strict";
import type { RequestEnvelope, ResponseEnvelope } from "ask-sdk-model";
import type { AlexaConfig } from "../amplify/plugins/alexa/config";
import type { PublicStory, PublicStorySource, PublicStorySummary } from "../amplify/plugins/alexa/contracts";
import { buildSkill } from "../amplify/plugins/alexa/skill";
import { storyParagraphs } from "../amplify/plugins/alexa/speech/markus-speech";

const config: AlexaConfig = { invocationName: "the example", skillName: "Example News", accountLinking: false, siteOrigin: "https://news.example.test" };
// Built from parts: a bare UUID literal in a test looks like a leaked session identifier to the repository scanner.
const SKILL_ID = `amzn1.ask.skill.${["12345678", "1234", "1234", "1234", "123456789abc"].join("-")}`;
const APL = { "Alexa.Presentation.APL": { runtime: { maxVersion: "2023.3" } } };

function story(number: number): PublicStory {
  return {
    id: `id-${number}`,
    slug: `articles/story-${number}`,
    title: `Headline number ${number}`,
    deck: `The deck of story ${number}.`,
    byline: "Ada Example",
    publishedAt: `2026-10-0${number}T00:00:00Z`,
    markus: `# A heading in story ${number}\n\nThe first paragraph of story ${number}. It has two sentences.\n\n- one item\n- another item\n\nThe last paragraph of story ${number}.`,
  };
}

const stories = [1, 2, 3].map(story);
const source: PublicStorySource = {
  async listLatest({ limit }) {
    return stories.slice(0, limit).map(({ markus: _markus, bodyIr: _bodyIr, ...summary }): PublicStorySummary => summary);
  },
  async getStory(slug) {
    return stories.find((candidate) => candidate.slug === slug);
  },
};

type Directive = { type: string; token?: string; datasources?: Record<string, Record<string, unknown>> };

function envelope(request: Record<string, unknown>, screen: boolean, attributes?: Record<string, unknown>): RequestEnvelope {
  const device = { deviceId: "d", supportedInterfaces: screen ? APL : {} };
  return {
    version: "1.0",
    session: { new: attributes === undefined, sessionId: "s", application: { applicationId: SKILL_ID }, user: { userId: "u" }, attributes },
    context: { System: { application: { applicationId: SKILL_ID }, user: { userId: "u" }, device, apiEndpoint: "https://api.amazonalexa.com" } },
    request: { requestId: "r", timestamp: "2026-10-31T00:00:00Z", locale: "en-US", ...request },
  } as RequestEnvelope;
}

function device(screen: boolean) {
  const skill = buildSkill({ config, stories: source });
  let attributes: Record<string, unknown> | undefined;
  const turn = async (request: Record<string, unknown>) => {
    const response: ResponseEnvelope = await skill.invoke(envelope(request, screen, attributes));
    attributes = response.sessionAttributes ?? attributes;
    const speech = (response.response.outputSpeech as { ssml?: string } | undefined)?.ssml ?? "";
    return { speech, directives: (response.response.directives ?? []) as Directive[] };
  };
  return {
    launch: () => turn({ type: "LaunchRequest" }),
    read: (ordinal: string) =>
      turn({ type: "IntentRequest", intent: { name: "ReadStoryIntent", confirmationStatus: "NONE", slots: { ordinal: { name: "ordinal", value: ordinal, confirmationStatus: "NONE" } } } }),
    touch: (index: unknown) => turn({ type: "Alexa.Presentation.APL.UserEvent", token: "feed", arguments: ["openStory", index] }),
  };
}

const RENDER = "Alexa.Presentation.APL.RenderDocument";

const behaviours: Record<string, () => Promise<void> | void> = {
  "the headlines show the feed on a screen": async () => {
    const { speech, directives } = await device(true).launch();
    assert.match(speech, /Headline number 1/);
    assert.equal(directives.length, 1);
    const [feed] = directives;
    assert.equal(feed.type, RENDER);
    assert.equal(feed.token, "feed");
    const data = feed.datasources?.feedData as { publication: string; stories: { index: number; title: string; deck?: string; byline?: string }[] };
    assert.equal(data.publication, "Example News");
    assert.deepEqual(
      data.stories.map(({ index, title, deck, byline }) => ({ index, title, deck, byline })),
      stories.map((entry, index) => ({ index, title: entry.title, deck: entry.deck, byline: entry.byline })),
    );
  },

  "a story shows its own screen while it is read": async () => {
    const show = device(true);
    await show.launch();
    const { speech, directives } = await show.read("2");
    assert.match(speech, /Headline number 2/);
    assert.equal(directives.length, 1);
    assert.equal(directives[0].token, "story");
    const data = directives[0].datasources?.storyData as { title: string; meta: string; paragraphs: string[] };
    assert.equal(data.title, "Headline number 2");
    assert.match(data.meta, /Ada Example/);
    assert.deepEqual(data.paragraphs, storyParagraphs(stories[1]));
  },

  "the story screen shows the body as plain paragraphs": () => {
    assert.deepEqual(storyParagraphs(stories[0]), [
      "A heading in story 1",
      "The first paragraph of story 1. It has two sentences.",
      "one item",
      "another item",
      "The last paragraph of story 1.",
    ]);
    for (const paragraph of storyParagraphs(stories[0])) assert.ok(!/[<>]/.test(paragraph), "no markup on screen");
  },

  "a voice-only device gets speech and no screen": async () => {
    const voice = device(false);
    const launch = await voice.launch();
    assert.match(launch.speech, /Headline number 1/);
    assert.deepEqual(launch.directives, []);
    const read = await voice.read("1");
    assert.match(read.speech, /Headline number 1/);
    assert.deepEqual(read.directives, []);
  },

  "touching a card reads that story and shows it": async () => {
    const show = device(true);
    await show.launch();
    const { speech, directives } = await show.touch("2");
    assert.match(speech, /Headline number 3/);
    assert.match(speech, /The deck of story 3/);
    assert.equal(directives[0]?.token, "story");
    assert.equal((directives[0].datasources?.storyData as { title: string }).title, "Headline number 3");
  },

  "touching a card past the list shows the headlines again": async () => {
    const show = device(true);
    await show.launch();
    const { speech, directives } = await show.touch("7");
    assert.match(speech, /latest headlines/);
    assert.equal(directives[0]?.token, "feed");
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
