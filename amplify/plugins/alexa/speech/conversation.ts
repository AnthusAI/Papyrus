/**
 * The spoken conversation the intents share: the headline list, one story, and the position kept in session attributes.
 * Every string spoken about the publication comes from the site's config or from its content; nothing here names a site.
 */
import type { HandlerInput } from "ask-sdk-core";
import type { Response } from "ask-sdk-model";
import { supportsApl } from "../apl/support/device";
import { feedDirective, storyDirective, type RenderDocumentDirective } from "../apl/support/directives";
import { themeFromConfig } from "../apl/support/theme";
import type { PublicStorySummary, SkillDependencies } from "../contracts";
import { storyBodyUnits, storyParagraphs } from "./markus-speech";
import { escapeSsml, fitUnits, MAX_SSML_LENGTH, pause, sentence, splitSentences, wrapSpeak } from "./ssml";

/** How many headlines a launch reads: what a spoken list holds before a listener loses track. */
export const HEADLINE_COUNT = 5;
const SESSION_KEY = "alexaPosition";

export type Headline = { slug: string; title: string; deck?: string; byline?: string };
/** Where the listener is: `current` is the index of the story being read, or `null` while they are at the headline list. */
export type Position = { headlines: Headline[]; current: number | null };

function readPosition(handlerInput: HandlerInput): Position | undefined {
  const value = handlerInput.attributesManager.getSessionAttributes()[SESSION_KEY] as Position | undefined;
  return value !== undefined && Array.isArray(value.headlines) && value.headlines.length > 0 ? value : undefined;
}

export function savePosition(handlerInput: HandlerInput, position: Position): void {
  handlerInput.attributesManager.setSessionAttributes({ ...handlerInput.attributesManager.getSessionAttributes(), [SESSION_KEY]: position });
}

function toHeadlines(stories: readonly PublicStorySummary[]): Headline[] {
  return stories.map(({ slug, title, deck, byline }) => ({ slug, title, ...(deck ? { deck } : {}), ...(byline ? { byline } : {}) }));
}

/** Puts a screen on devices that have one; voice-only devices get the speech alone. */
function show(handlerInput: HandlerInput, directive: () => RenderDocumentDirective): void {
  if (supportsApl(handlerInput.requestEnvelope)) handlerInput.responseBuilder.addDirective(directive());
}

export function say(handlerInput: HandlerInput, ssml: string, reprompt: string): Response {
  return handlerInput.responseBuilder.speak(ssml).reprompt(reprompt).withShouldEndSession(false).getResponse();
}

export function sayAndEnd(handlerInput: HandlerInput, ssml: string): Response {
  return handlerInput.responseBuilder.speak(ssml).withShouldEndSession(true).getResponse();
}

/** The position in session attributes, or a fresh headline list when the session has none. */
export async function currentPosition(handlerInput: HandlerInput, dependencies: SkillDependencies): Promise<Position | undefined> {
  const existing = readPosition(handlerInput);
  if (existing !== undefined) return existing;
  const headlines = toHeadlines(await dependencies.stories.listLatest({ limit: HEADLINE_COUNT }));
  return headlines.length > 0 ? { headlines, current: null } : undefined;
}

export const NOTHING_PUBLISHED = wrapSpeak(sentence("There are no published stories yet. Please try again later."));

const HEADLINE_PROMPT = "Which one would you like to hear? Say the number, like the second one.";
const HEADLINE_REPROMPT = "Say the number of the story you want to hear, or say help.";

/** Reads the headlines (the position's, or fresh ones) and asks which story. */
export async function readHeadlines(
  handlerInput: HandlerInput,
  dependencies: SkillDependencies,
  options: { greeting?: string; fresh?: boolean; position?: Position } = {},
): Promise<Response> {
  let headlines = options.fresh ? undefined : (options.position ?? readPosition(handlerInput))?.headlines;
  if (headlines === undefined) headlines = toHeadlines(await dependencies.stories.listLatest({ limit: HEADLINE_COUNT }));
  if (headlines.length === 0) return sayAndEnd(handlerInput, NOTHING_PUBLISHED);

  const intro = `${options.greeting ?? ""} Here are the latest headlines from ${dependencies.config.skillName}.`.trim();
  const closing = sentence(HEADLINE_PROMPT);
  const items = headlines.map((headline, index) => `<s>${index + 1}.<break time="250ms"/> ${escapeSsml(headline.title)}</s>${pause(400)}`);
  const introSsml = splitSentences(intro).map(sentence).join("");
  const room = MAX_SSML_LENGTH - wrapSpeak(introSsml + closing).length;
  const listed = fitUnits(items, room);
  savePosition(handlerInput, { headlines, current: null });
  const shown = headlines;
  show(handlerInput, () =>
    feedDirective(
      shown.map((headline) => ({ id: headline.slug, publishedAt: "", ...headline })),
      themeFromConfig(dependencies.config),
      dependencies.config.skillName,
    ),
  );
  return say(handlerInput, wrapSpeak(introSsml + listed.ssml + closing), wrapSpeak(sentence(HEADLINE_REPROMPT)));
}

/** The slot value as a 1-based story number: Alexa resolves "second" to "2" for AMAZON.Ordinal and speaks digits for AMAZON.NUMBER. */
export function storyNumber(...values: (string | null | undefined)[]): number | undefined {
  for (const value of values) {
    if (value == null || value.trim() === "") continue;
    const parsed = Number.parseInt(value, 10);
    if (Number.isInteger(parsed)) return parsed;
  }
  return undefined;
}

const NEXT_OFFER = "Say next for the next story, previous to go back, repeat to hear it again, or stop.";
const LAST_OFFER = "That was the last of the latest stories. Say previous to go back, headlines for the list again, or stop.";
const TRUNCATION_NOTICE = "That is as much of this story as I can read aloud.";

/** Reads one story: title, byline, deck and as much of the body as fits, then what to say next. */
export async function readStory(
  handlerInput: HandlerInput,
  dependencies: SkillDependencies,
  position: Position,
  index: number,
): Promise<Response> {
  const headline = position.headlines[index];
  const story = await dependencies.stories.getStory(headline.slug);
  if (story === undefined) {
    return readHeadlines(handlerInput, dependencies, { greeting: "I could not find that story any more.", fresh: true });
  }

  const offer = sentence(index + 1 < position.headlines.length ? NEXT_OFFER : LAST_OFFER);
  const opening: string[] = [sentence(story.title)];
  if (story.byline) opening.push(sentence(`By ${story.byline}`));
  opening.push(pause(500));
  if (story.deck) opening.push(...splitSentences(story.deck).map(sentence), pause(500));

  const reserved = wrapSpeak(offer + sentence(TRUNCATION_NOTICE) + pause(500)).length;
  const room = MAX_SSML_LENGTH - reserved;
  const head = fitUnits(opening, room);
  let body = { ssml: "", truncated: head.truncated };
  if (!head.truncated) body = fitUnits(storyBodyUnits(story), room - head.ssml.length);
  const notice = body.truncated ? sentence(TRUNCATION_NOTICE) : "";

  savePosition(handlerInput, { headlines: position.headlines, current: index });
  show(handlerInput, () => storyDirective(story, storyParagraphs(story), themeFromConfig(dependencies.config)));
  return say(handlerInput, wrapSpeak(head.ssml + body.ssml + pause(500) + notice + offer), wrapSpeak(sentence(NEXT_OFFER)));
}

/** Opens the story at `index` of the headline list (a touched card on the feed screen): the same reading a spoken request gets. */
export async function openStoryAt(handlerInput: HandlerInput, index: number, dependencies: SkillDependencies): Promise<Response> {
  const position = await currentPosition(handlerInput, dependencies);
  if (position === undefined) return sayAndEnd(handlerInput, NOTHING_PUBLISHED);
  if (index >= position.headlines.length) return readHeadlines(handlerInput, dependencies, { position });
  return readStory(handlerInput, dependencies, position, index);
}
