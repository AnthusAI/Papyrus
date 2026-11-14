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
export type Position = { headlines: Headline[]; current: number | null; part?: number };

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

/** The welcome for the first request of a session (Alexa+ often opens a skill with an intent, not a launch). */
export function welcomeIfNew(handlerInput: HandlerInput, dependencies: SkillDependencies): string | undefined {
  return handlerInput.requestEnvelope.session?.new ? `Welcome to ${dependencies.config.skillName}.` : undefined;
}

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
const CONTINUE_OFFER = "Say continue to keep reading, or next for the next story.";
const END_NOTICE = "That is the end of the story.";

/**
 * How much of a story one reply speaks. Alexa turns the whole reply into speech before it says a word, so a reply near the
 * 8000-character limit leaves the listener waiting; a part this size starts within a couple of seconds (about a minute of speech).
 */
export const STORY_PART_LENGTH = 1800;

function storyOpening(story: { title: string; byline?: string; deck?: string }): string[] {
  const opening = [sentence(story.title)];
  if (story.byline) opening.push(sentence(spokenByline(story.byline)));
  opening.push(pause(500));
  if (story.deck) opening.push(...splitSentences(story.deck).map(sentence), pause(500));
  return opening;
}

function storyOpeningLength(story: { title: string; byline?: string; deck?: string }): number {
  return storyOpening(story).join("").length;
}

/** "By Ada" for "Ada", unchanged for a byline that already says "by ...". */
export function spokenByline(byline: string): string {
  return /^by\s/i.test(byline.trim()) ? byline.trim() : `By ${byline.trim()}`;
}

/**
 * The body's units cut into parts, always between units (a unit longer than a part gets a part to itself). The first part holds
 * `firstLength` characters, the rest `length`, so a part that follows the opening is no slower to start than the others.
 */
export function storyParts(units: readonly string[], firstLength: number, length: number): string[][] {
  const parts: string[][] = [];
  let part: string[] = [];
  let used = 0;
  for (const unit of units) {
    const limit = parts.length === 0 ? firstLength : length;
    if (part.length > 0 && used + unit.length > limit) {
      parts.push(part);
      part = [];
      used = 0;
    }
    part.push(unit);
    used += unit.length;
  }
  if (part.some((unit) => !unit.startsWith("<break"))) parts.push(part);
  return parts;
}

/**
 * Reads part `part` of one story. Part 0 opens with the title, byline and deck. Each reply is one short part, then what to say
 * next: continue while parts remain, otherwise next (or the end of the list).
 */
export async function readStory(
  handlerInput: HandlerInput,
  dependencies: SkillDependencies,
  position: Position,
  index: number,
  part = 0,
): Promise<Response> {
  const headline = position.headlines[index];
  const story = await dependencies.stories.getStory(headline.slug);
  if (story === undefined) {
    return readHeadlines(handlerInput, dependencies, { greeting: "I could not find that story any more.", fresh: true });
  }

  const opening = part === 0 ? storyOpening(story) : [];
  // The first part shares its length with the opening (title, byline, deck), so every part starts about as quickly.
  const parts = storyParts(storyBodyUnits(story), Math.max(400, STORY_PART_LENGTH - storyOpeningLength(story)), STORY_PART_LENGTH);
  const body = parts[part] ?? [];
  const remaining = part + 1 < parts.length;

  const isLast = index + 1 >= position.headlines.length;
  const offer = remaining ? sentence(CONTINUE_OFFER) : sentence(END_NOTICE) + sentence(isLast ? LAST_OFFER : NEXT_OFFER);
  const room = MAX_SSML_LENGTH - wrapSpeak(pause(500) + offer).length;
  const spoken = fitUnits([...opening, ...body], room);

  savePosition(handlerInput, { headlines: position.headlines, current: index, part });
  if (part === 0) show(handlerInput, () => storyDirective(story, storyParagraphs(story), themeFromConfig(dependencies.config)));
  return say(handlerInput, wrapSpeak(spoken.ssml + pause(500) + offer), wrapSpeak(sentence(remaining ? CONTINUE_OFFER : NEXT_OFFER)));
}

/** Opens the story at `index` of the headline list (a touched card on the feed screen): the same reading a spoken request gets. */
export async function openStoryAt(handlerInput: HandlerInput, index: number, dependencies: SkillDependencies): Promise<Response> {
  const position = await currentPosition(handlerInput, dependencies);
  if (position === undefined) return sayAndEnd(handlerInput, NOTHING_PUBLISHED);
  if (index >= position.headlines.length) return readHeadlines(handlerInput, dependencies, { position });
  return readStory(handlerInput, dependencies, position, index);
}
