/**
 * Reviewing References by voice: the editor hears one Reference at a time (title, subtitle, summary), says accept or reject (with
 * a reason) or skip, and the skill moves on. Two queues: "best bets" (the Cyclotron's P(accept), highest first, as the newsroom's
 * Best bets sort) and "needs my help" (the References the Cyclotron is least sure about, as the newsroom's "What needs me").
 *
 * The queue lives in the session (ids and titles only); each Reference's text is fetched when it is read. Votes go through the
 * newsroom's own mutation under the editor's token (review/newsroom.ts).
 */
import type { HandlerInput } from "ask-sdk-core";
import type { Response } from "ask-sdk-model";
import { UNDECIDED_PROBABILITY, UNRECORDED_CONFIDENCE } from "../../../../lib/reference-feed-ranking";
import { uncertaintyOf } from "../../../../lib/needs-me-ranking";
import { rejectionReasonCodeForWrittenReason } from "../../../../lib/reference-policy";
import { supportsApl } from "../apl/support/device";
import { themeFromConfig } from "../apl/support/theme";
import { linkAccountResponse, linkedUser, type LinkedUser } from "../auth";
import type { SkillDependencies } from "../contracts";
import { fitUnits, pause, sentence, splitSentences, wrapSpeak } from "../speech/ssml";
import { referenceDirective } from "./card";
import { NewsroomRefusedError, type NewsroomReview, type ReviewCandidate, type ReviewDetails } from "./newsroom";

export type ReviewQueueKind = "best" | "help";

export const QUEUE_NAMES: Record<ReviewQueueKind, string> = { best: "best bets", help: "needs your help" };

/** How many unrated References a queue reads to order (the needs-my-help order needs them all in view). */
export const QUEUE_SCAN_LIMIT = 300;
/** How many a session carries: enough for a sitting, small enough for Alexa's session attribute limit. */
export const QUEUE_SESSION_LIMIT = 25;
/** How much of a summary one turn speaks: the editor can ask for more. */
export const SUMMARY_LENGTH = 900;
export const EDITOR_GROUPS = ["editor", "admin"];

const SESSION_KEY = "alexaReview";

type QueueEntry = Pick<ReviewCandidate, "id" | "lineageId" | "title" | "sourceUri" | "sourcePublishedAt" | "probability">;

export type ReviewState = {
  kind: ReviewQueueKind;
  queue: QueueEntry[];
  /** How many unrated References the queue was taken from (the queue itself is capped). */
  total: number;
  position: number;
  /** The last vote, so "undo" can reopen it. */
  lastVote?: { index: number; action: "accept" | "reject" };
  /** True after "reject" with no reason: the next "because ..." completes it. */
  awaitingReason?: boolean;
  /** The full prompt is said the first time; after that the short one. */
  heardPrompt?: boolean;
  /** The current Reference's decision, for the vote and for "why". */
  decision?: ReviewDetails["decision"];
};

export function reviewState(handlerInput: HandlerInput): ReviewState | undefined {
  const value = handlerInput.attributesManager.getSessionAttributes()[SESSION_KEY] as ReviewState | undefined;
  return value && Array.isArray(value.queue) ? value : undefined;
}

export function saveReviewState(handlerInput: HandlerInput, state: ReviewState | undefined): void {
  const attributes = { ...handlerInput.attributesManager.getSessionAttributes() };
  if (state) attributes[SESSION_KEY] = state;
  else delete attributes[SESSION_KEY];
  handlerInput.attributesManager.setSessionAttributes(attributes);
}

/** True while the editor is in a review: the shared intents (next, repeat, help, stop, fallback) then mean review things. */
export function inReview(handlerInput: HandlerInput): boolean {
  return reviewState(handlerInput) !== undefined;
}

/** The queue in its order. Best bets: P(accept) highest first. Needs my help: most uncertain first. Ties: newest first, then id. */
export function orderQueue(candidates: readonly ReviewCandidate[], kind: ReviewQueueKind): ReviewCandidate[] {
  const probability = (candidate: ReviewCandidate) => candidate.probability ?? UNDECIDED_PROBABILITY;
  const key = kind === "best" ? probability : (candidate: ReviewCandidate) => uncertaintyOf(probability(candidate));
  return [...candidates].sort(
    (left, right) =>
      key(right) - key(left) ||
      (Date.parse(right.arrivedAt ?? "") || 0) - (Date.parse(left.arrivedAt ?? "") || 0) ||
      left.id.localeCompare(right.id),
  );
}

function say(handlerInput: HandlerInput, ssml: string, reprompt: string): Response {
  return handlerInput.responseBuilder.speak(wrapSpeak(ssml)).reprompt(wrapSpeak(reprompt)).withShouldEndSession(false).getResponse();
}

const NOT_AN_EDITOR = "Reviewing references is for this newsroom's editors, and your account is not one. You can still hear the latest stories: say headlines.";
const LINK_FOR_REVIEW =
  "To review references I need to know it's you. Open the Alexa app, or scan the code on your screen, and sign in with Google. Then ask me again.";

/**
 * Runs `signedIn` for a linked editor with a newsroom bound to their token. Not linked: the LinkAccount response (an Echo Show
 * shows Amazon's QR code). Linked but not an editor: says so and offers the stories.
 */
export async function asEditor(
  handlerInput: HandlerInput,
  dependencies: SkillDependencies,
  signedIn: (review: NewsroomReview, user: LinkedUser) => Promise<Response>,
): Promise<Response> {
  const user = await linkedUser(handlerInput, dependencies.tokens);
  const accessToken = handlerInput.requestEnvelope.context?.System?.user?.accessToken;
  if (!user || !accessToken) return linkAccountResponse(handlerInput, LINK_FOR_REVIEW);
  if (!user.groups.some((group) => EDITOR_GROUPS.includes(group))) {
    saveReviewState(handlerInput, undefined);
    return say(handlerInput, sentence(NOT_AN_EDITOR), sentence("Say headlines, or stop."));
  }
  if (!dependencies.review) return say(handlerInput, sentence("Reviewing references is not set up for this site yet."), sentence("Say headlines, or stop."));
  try {
    return await signedIn(dependencies.review(accessToken), user);
  } catch (error) {
    if (error instanceof NewsroomRefusedError) return linkAccountResponse(handlerInput, "The newsroom did not accept your sign-in. Please link your account again in the Alexa app, then ask me again.");
    console.error("alexa review failed", error);
    return say(handlerInput, sentence("Sorry, I couldn't reach the newsroom just now. Try again in a moment."), sentence("Say try again, or stop."));
  }
}

/** Starts (or restarts) a queue and reads its first Reference. */
export async function startQueue(handlerInput: HandlerInput, dependencies: SkillDependencies, review: NewsroomReview, kind: ReviewQueueKind, lead = ""): Promise<Response> {
  const candidates = orderQueue(await review.listUnrated(QUEUE_SCAN_LIMIT), kind);
  if (candidates.length === 0) {
    saveReviewState(handlerInput, undefined);
    return say(handlerInput, `${lead}${sentence("There's nothing waiting for review. Every reference has an answer.")}`, sentence("Say headlines for the latest stories, or stop."));
  }
  const queue = candidates.slice(0, QUEUE_SESSION_LIMIT).map(({ id, lineageId, title, sourceUri, sourcePublishedAt, probability }) => ({
    id,
    lineageId,
    title,
    ...(sourceUri ? { sourceUri } : {}),
    ...(sourcePublishedAt ? { sourcePublishedAt } : {}),
    ...(probability === undefined ? {} : { probability }),
  }));
  const state: ReviewState = { kind, queue, total: candidates.length, position: 0 };
  const count = candidates.length === 1 ? "One reference is waiting" : `${candidates.length} references are waiting`;
  const order = kind === "best" ? "starting with the ones I think you'll like most" : "starting with the ones I'm least sure about";
  return readCurrent(handlerInput, dependencies, review, state, `${lead}${sentence(`${count}, ${order}.`)}`);
}

function spokenSummary(details: ReviewDetails): string {
  const parts: string[] = [];
  if (details.deck) parts.push(...splitSentences(details.deck).map(sentence));
  if (details.summary && details.summary !== details.deck) parts.push(...splitSentences(details.summary).map(sentence));
  return fitUnits(parts, SUMMARY_LENGTH).ssml;
}

const FULL_PROMPT = "Say accept, or reject and why, like reject because it's off topic. Or say skip.";
const SHORT_PROMPT = "Accept, reject, or skip?";

/** Reads the Reference at `state.position` (title, where it is from, subtitle, summary) and asks for a decision. */
export async function readCurrent(
  handlerInput: HandlerInput,
  dependencies: SkillDependencies,
  review: NewsroomReview,
  state: ReviewState,
  lead = "",
): Promise<Response> {
  if (state.position >= state.queue.length) return finishQueue(handlerInput, state, lead);
  const entry = state.queue[state.position];
  const details = await review.details(entry);
  const position = `Number ${state.position + 1} of ${state.total}.`;
  const prompt = state.heardPrompt ? SHORT_PROMPT : FULL_PROMPT;
  const next: ReviewState = { ...state, heardPrompt: true, awaitingReason: false, decision: details.decision };
  saveReviewState(handlerInput, next);
  if (supportsApl(handlerInput.requestEnvelope)) {
    handlerInput.responseBuilder.addDirective(
      referenceDirective({ ...details, position: state.position + 1, total: state.total, queueName: QUEUE_NAMES[state.kind] }, themeFromConfig(dependencies.config)),
    );
  }
  const from = details.siteName ? sentence(`From ${details.siteName}.`) : "";
  const summary = spokenSummary(details);
  const noText = summary ? "" : sentence("There's no summary yet, only the title.");
  return say(handlerInput, `${lead}${sentence(position)}${sentence(details.title)}${from}${pause(300)}${summary}${noText}${pause(400)}${sentence(prompt)}`, sentence(SHORT_PROMPT));
}

function finishQueue(handlerInput: HandlerInput, state: ReviewState, lead: string): Response {
  const other: ReviewQueueKind = state.kind === "best" ? "help" : "best";
  const more = state.total > state.queue.length ? ` There are more waiting: say ${QUEUE_NAMES[state.kind]} again to continue.` : "";
  saveReviewState(handlerInput, { ...state, position: state.queue.length });
  return say(
    handlerInput,
    `${lead}${sentence(`That's the end of this round.${more}`)}${sentence(`Say ${QUEUE_NAMES[other]} for the other list, or stop.`)}`,
    sentence(`Say ${QUEUE_NAMES[other]}, or stop.`),
  );
}

/** Records accept or reject for the current Reference, then reads the next one. A reject needs a reason in words. */
export async function vote(
  handlerInput: HandlerInput,
  dependencies: SkillDependencies,
  action: "accept" | "reject",
  reason?: string,
): Promise<Response> {
  return asEditor(handlerInput, dependencies, async (review, user) => {
    const state = reviewState(handlerInput);
    if (!state || state.position >= state.queue.length) return notReviewing(handlerInput);
    const entry = state.queue[state.position];
    const note = reason?.trim() || undefined;
    if (action === "reject" && !note) {
      saveReviewState(handlerInput, { ...state, awaitingReason: true });
      return say(handlerInput, sentence("Why? Say because, and the reason. For example, because it's a press release."), sentence("Say because, and the reason. Or say skip."));
    }
    const actorLabel = (await review.editorEmail()) ?? user.email ?? undefined;
    const result = await review.vote({
      referenceId: entry.id,
      action,
      ...(note ? { note } : {}),
      ...(action === "reject" ? { reasonCode: rejectionReasonCodeForWrittenReason(note) ?? "other" } : {}),
      ...(state.decision ? { decisionRelationId: state.decision.decisionRelationId } : {}),
      ...(actorLabel ? { actorLabel } : {}),
    });
    if (!result.ok) {
      if (result.refused) return linkAccountResponse(handlerInput, "The newsroom didn't accept your sign-in, so nothing was recorded. Please link your account again in the Alexa app.");
      return say(handlerInput, sentence(`I couldn't record that, so nothing changed. Say ${action} again to retry, or skip.`), sentence(SHORT_PROMPT));
    }
    const confirmation = action === "accept" ? "Accepted." : "Rejected.";
    return readCurrent(handlerInput, dependencies, review, { ...state, position: state.position + 1, lastVote: { index: state.position, action }, awaitingReason: false }, sentence(confirmation));
  });
}

/** Skip: on to the next one, nothing recorded. */
export async function skip(handlerInput: HandlerInput, dependencies: SkillDependencies): Promise<Response> {
  return asEditor(handlerInput, dependencies, async (review) => {
    const state = reviewState(handlerInput);
    if (!state) return notReviewing(handlerInput);
    return readCurrent(handlerInput, dependencies, review, { ...state, position: state.position + 1, awaitingReason: false }, sentence("Skipped."));
  });
}

/** Undo: reopens the last vote (back to unrated) and reads that Reference again. */
export async function undo(handlerInput: HandlerInput, dependencies: SkillDependencies): Promise<Response> {
  return asEditor(handlerInput, dependencies, async (review) => {
    const state = reviewState(handlerInput);
    if (!state?.lastVote) return say(handlerInput, sentence("There's nothing to undo yet."), sentence(SHORT_PROMPT));
    const entry = state.queue[state.lastVote.index];
    const result = await review.vote({ referenceId: entry.id, action: "reopen" });
    if (!result.ok) return say(handlerInput, sentence("I couldn't undo that just now. It's still recorded as you said."), sentence(SHORT_PROMPT));
    const undone = state.lastVote.action === "accept" ? "Undone: that one is no longer accepted." : "Undone: that one is no longer rejected.";
    return readCurrent(handlerInput, dependencies, review, { ...state, position: state.lastVote.index, lastVote: undefined }, sentence(undone));
  });
}

/** Repeat: the current Reference again. */
export async function repeatCurrent(handlerInput: HandlerInput, dependencies: SkillDependencies): Promise<Response> {
  return asEditor(handlerInput, dependencies, async (review) => {
    const state = reviewState(handlerInput);
    if (!state) return notReviewing(handlerInput);
    return readCurrent(handlerInput, dependencies, review, state);
  });
}

/** Previous: back one Reference (it may already have an answer; voting again replaces it). */
export async function previous(handlerInput: HandlerInput, dependencies: SkillDependencies): Promise<Response> {
  return asEditor(handlerInput, dependencies, async (review) => {
    const state = reviewState(handlerInput);
    if (!state) return notReviewing(handlerInput);
    if (state.position === 0) return readCurrent(handlerInput, dependencies, review, state, sentence("This is the first one."));
    return readCurrent(handlerInput, dependencies, review, { ...state, position: state.position - 1 });
  });
}

/** "More", "the whole summary": everything there is about the current Reference, as much as one reply can say. */
export async function moreDetail(handlerInput: HandlerInput, dependencies: SkillDependencies): Promise<Response> {
  return asEditor(handlerInput, dependencies, async (review) => {
    const state = reviewState(handlerInput);
    if (!state || state.position >= state.queue.length) return notReviewing(handlerInput);
    const details = await review.details(state.queue[state.position]);
    const parts = [details.deck, details.summary !== details.deck ? details.summary : undefined].filter((part): part is string => Boolean(part)).flatMap((part) => splitSentences(part).map(sentence));
    if (parts.length === 0) return say(handlerInput, `${sentence("That's all there is: only the title. Say send it to my phone to read the source.")}${sentence(SHORT_PROMPT)}`, sentence(SHORT_PROMPT));
    const reply = fitUnits(parts, 6000);
    const cut = reply.truncated ? sentence("That's as much as I can read. Say send it to my phone for the rest.") : "";
    return say(handlerInput, `${reply.ssml}${cut}${pause(400)}${sentence(SHORT_PROMPT)}`, sentence(SHORT_PROMPT));
  });
}

/** How many are left. */
export function remaining(handlerInput: HandlerInput): Response {
  const state = reviewState(handlerInput);
  if (!state) return notReviewing(handlerInput);
  const left = Math.max(0, state.total - state.position);
  const phrase = left === 0 ? "None are left in this round." : left === 1 ? "This is the last one." : `${left} are left, counting this one.`;
  return say(handlerInput, `${sentence(phrase)}${sentence(SHORT_PROMPT)}`, sentence(SHORT_PROMPT));
}

/** Why this one: the Cyclotron's guess in plain words. */
export function why(handlerInput: HandlerInput): Response {
  const state = reviewState(handlerInput);
  if (!state || state.position >= state.queue.length) return notReviewing(handlerInput);
  const entry = state.queue[state.position];
  const decision = state.decision;
  // The same reading as the newsroom's acceptProbability: the confidence is in the label the Cyclotron chose.
  const confidence = decision ? (decision.confidence ?? UNRECORDED_CONFIDENCE) : undefined;
  const probability =
    decision && confidence !== undefined ? (decision.label === (decision.positiveLabel ?? "include") ? confidence : 1 - confidence) : entry.probability;
  let reason: string;
  if (probability === undefined) reason = "The Cyclotron hasn't made a guess about this one yet.";
  else {
    const percent = Math.round(probability * 100);
    const lean = probability >= 0.5 ? `thinks you'd accept it, about ${percent} percent sure` : `thinks you'd reject it, about ${100 - percent} percent sure`;
    reason = `The Cyclotron ${lean}.`;
  }
  const asked = decision?.reviewRecommended ? (decision.reviewReason === "audit" ? " It picked this one at random to check its work." : " It asked for your help with this one.") : "";
  const queue = state.kind === "help" ? " It's in this list because that guess is close to a coin toss." : "";
  return say(handlerInput, `${sentence(`${reason}${asked}${queue}`)}${sentence(SHORT_PROMPT)}`, sentence(SHORT_PROMPT));
}

/** Who published it and when. */
export async function source(handlerInput: HandlerInput, dependencies: SkillDependencies): Promise<Response> {
  return asEditor(handlerInput, dependencies, async (review) => {
    const state = reviewState(handlerInput);
    if (!state || state.position >= state.queue.length) return notReviewing(handlerInput);
    const details = await review.details(state.queue[state.position]);
    const host = details.sourceUri ? safeHost(details.sourceUri) : undefined;
    const who = details.siteName ?? host;
    const when = details.sourcePublishedAt ? spokenDate(details.sourcePublishedAt) : undefined;
    const parts = [who ? `It's from ${who}` : "I don't know who published it", when ? `, published ${when}.` : "."].join("");
    return say(handlerInput, `${sentence(parts)}${sentence(SHORT_PROMPT)}`, sentence(SHORT_PROMPT));
  });
}

/** Send to phone: a card in the Alexa app with the title and the link. */
export async function sendToPhone(handlerInput: HandlerInput, dependencies: SkillDependencies): Promise<Response> {
  return asEditor(handlerInput, dependencies, async (review) => {
    const state = reviewState(handlerInput);
    if (!state || state.position >= state.queue.length) return notReviewing(handlerInput);
    const details = await review.details(state.queue[state.position]);
    if (!details.sourceUri) return say(handlerInput, `${sentence("This one has no link to send.")}${sentence(SHORT_PROMPT)}`, sentence(SHORT_PROMPT));
    handlerInput.responseBuilder.withSimpleCard(details.title.slice(0, 120), `${details.deck ? `${details.deck}\n\n` : ""}${details.sourceUri}`);
    return say(handlerInput, `${sentence("I sent the link to the Alexa app on your phone.")}${sentence(SHORT_PROMPT)}`, sentence(SHORT_PROMPT));
  });
}

/** "Accept all" and the like: one at a time, kindly. */
export function bulkRefused(handlerInput: HandlerInput): Response {
  return say(handlerInput, `${sentence("I'll only take them one at a time, so each answer is a real one.")}${sentence(SHORT_PROMPT)}`, sentence(SHORT_PROMPT));
}

export function reviewHelp(handlerInput: HandlerInput): Response {
  const state = reviewState(handlerInput);
  const where = state ? `You're in ${QUEUE_NAMES[state.kind]}, number ${Math.min(state.position + 1, state.total)} of ${state.total}. ` : "";
  return say(
    handlerInput,
    sentence(
      `${where}Say accept, or reject and why. Skip moves on without answering. Undo takes back your last answer. You can also ask why this one, who published it, how many are left, or say send it to my phone. Say best bets or needs my help to switch lists, or stop.`,
    ),
    sentence(SHORT_PROMPT),
  );
}

export function notReviewing(handlerInput: HandlerInput): Response {
  return say(handlerInput, sentence("We're not reviewing anything right now. Say needs my help, or best bets, to start."), sentence("Say needs my help, best bets, or headlines."));
}

export function stopReview(handlerInput: HandlerInput): Response {
  const state = reviewState(handlerInput);
  saveReviewState(handlerInput, undefined);
  const skipped = state && state.position < state.total ? " Anything you didn't answer will still be waiting." : "";
  return handlerInput.responseBuilder.speak(wrapSpeak(sentence(`Okay, stopping.${skipped}`))).withShouldEndSession(true).getResponse();
}

function safeHost(uri: string): string | undefined {
  try {
    return new URL(uri).hostname.replace(/^www\./, "");
  } catch {
    return undefined;
  }
}

function spokenDate(value: string): string | undefined {
  const time = Date.parse(value);
  if (Number.isNaN(time)) return undefined;
  return new Date(time).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
}

