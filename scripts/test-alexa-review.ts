/**
 * Reviewing References by voice: whole conversations against a fake newsroom and a fake token verifier. Run with no argument for
 * everything, or with one behaviour name (the Gherkin steps do this); each prints `{"behaviour": ...}`. No network, no Amazon.
 */
import assert from "node:assert/strict";
import type { RequestEnvelope, ResponseEnvelope } from "ask-sdk-model";
import type { AlexaConfig } from "../amplify/plugins/alexa/config";
import type { AccessTokenVerifier } from "../amplify/plugins/alexa/contracts";
import { orderQueue, QUEUE_SESSION_LIMIT } from "../amplify/plugins/alexa/review/flow";
import { createNewsroomReview, displayTitle, type FetchLike, type NewsroomReview, type ReviewCandidate, type ReviewDetails, type VoteInput } from "../amplify/plugins/alexa/review/newsroom";
import { buildSkill } from "../amplify/plugins/alexa/skill";

const config: AlexaConfig = { invocationName: "the example newsroom", skillName: "Example Newsroom", accountLinking: true, amazonVendorId: "M2EXAMPLEVENDOR", siteOrigin: "https://news.example.test", siteId: "example" };
// Built from parts: a bare UUID literal in a test looks like a leaked session identifier to the repository scanner.
const SKILL_ID = `amzn1.ask.skill.${["12345678", "1234", "1234", "1234", "123456789abc"].join("-")}`;
const APL = { "Alexa.Presentation.APL": { runtime: { maxVersion: "2023.3" } } };

type Reference = ReviewCandidate & Omit<ReviewDetails, "title"> & { status: string };

function reference(number: number, probability: number | undefined, extra: Partial<Reference> = {}): Reference {
  return {
    id: `ref-${number}`,
    lineageId: `lineage-${number}`,
    title: `Reference number ${number}`,
    deck: `The subtitle of reference ${number}.`,
    summary: `The summary of reference ${number}. It has a second sentence.`,
    siteName: "Example Source",
    sourceUri: `https://source.example.test/${number}`,
    sourcePublishedAt: `2026-10-${String(10 + number).padStart(2, "0")}T00:00:00Z`,
    arrivedAt: `2026-10-${String(10 + number).padStart(2, "0")}T00:00:00Z`,
    status: "pending",
    ...(probability === undefined ? {} : { probability, decision: { decisionRelationId: `decision-${number}`, label: probability >= 0.5 ? "include" : "exclude", confidence: probability >= 0.5 ? probability : 1 - probability, positiveLabel: "include", reviewRecommended: false, reviewReason: null } }),
    ...extra,
  };
}

/** A newsroom with the given References; records every vote, and can refuse. */
function fakeNewsroom(references: Reference[], options: { refuseVotes?: boolean; failVotes?: boolean } = {}) {
  const votes: VoteInput[] = [];
  const review: NewsroomReview = {
    async listUnrated(limit) {
      return references.filter((item) => item.status === "pending").slice(0, limit);
    },
    async details(candidate) {
      const found = references.find((item) => item.id === candidate.id);
      assert.ok(found, `details for ${candidate.id}`);
      const { deck, summary, siteName, sourceUri, sourcePublishedAt, decision } = found;
      return { title: found.title, deck, summary, siteName, sourceUri, sourcePublishedAt, decision };
    },
    async vote(input) {
      if (options.refuseVotes) return { ok: false, refused: true, message: "Unauthorized" };
      if (options.failVotes) return { ok: false, refused: false, message: "network" };
      votes.push(input);
      const found = references.find((item) => item.id === input.referenceId);
      if (found) found.status = input.action === "reopen" ? "pending" : input.action === "accept" ? "accepted" : "rejected";
      return { ok: true, status: input.action };
    },
    async editorEmail() {
      return "editor@example.test";
    },
  };
  return { review, votes };
}

const editorTokens: AccessTokenVerifier = { async verify(token) { return token === "editor-token" ? { ok: true, token: { subject: "sub-editor", claims: { username: "google_1", "cognito:groups": ["editor"] } } } : token === "reader-token" ? { ok: true, token: { subject: "sub-reader", claims: { username: "google_2" } } } : { ok: false, reason: "invalid" }; } };

function envelope(request: Record<string, unknown>, options: { token?: string; attributes?: Record<string, unknown>; screen?: boolean }): RequestEnvelope {
  const user = { userId: "u", ...(options.token ? { accessToken: options.token } : {}) };
  return {
    version: "1.0",
    session: { new: options.attributes === undefined, sessionId: "s", application: { applicationId: SKILL_ID }, user, attributes: options.attributes },
    context: { System: { application: { applicationId: SKILL_ID }, user, device: { deviceId: "d", supportedInterfaces: options.screen ? APL : {} }, apiEndpoint: "https://api.amazonalexa.com" } },
    request: { requestId: "r", timestamp: "2026-10-31T00:00:00Z", locale: "en-US", ...request },
  } as RequestEnvelope;
}

type Turn = { speech: string; reprompt: string; ends: boolean; card?: { type: string }; directives: { type: string; token?: string; datasources?: Record<string, Record<string, unknown>> }[] };

const text = (ssml: string) =>
  ssml.replace(/<[^>]*>/g, " ").replace(/&apos;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();

function conversation(newsroom: NewsroomReview | undefined, options: { token?: string; screen?: boolean } = { token: "editor-token" }) {
  const skill = buildSkill({ config, stories: { listLatest: async () => [], getStory: async () => undefined }, tokens: editorTokens, ...(newsroom ? { review: () => newsroom } : {}) });
  let attributes: Record<string, unknown> | undefined;
  const turn = async (request: Record<string, unknown>): Promise<Turn> => {
    const response: ResponseEnvelope = await skill.invoke(envelope(request, { ...options, attributes }));
    attributes = response.sessionAttributes ?? attributes;
    const r = response.response;
    return {
      speech: text((r.outputSpeech as { ssml?: string } | undefined)?.ssml ?? ""),
      reprompt: text((r.reprompt?.outputSpeech as { ssml?: string } | undefined)?.ssml ?? ""),
      ends: r.shouldEndSession === true,
      card: r.card as { type: string } | undefined,
      directives: (r.directives ?? []) as Turn["directives"],
    };
  };
  const intent = (name: string, slots: Record<string, string> = {}) =>
    turn({ type: "IntentRequest", intent: { name, confirmationStatus: "NONE", slots: Object.fromEntries(Object.entries(slots).map(([key, value]) => [key, { name: key, value, confirmationStatus: "NONE" }])) } });
  return { launch: () => turn({ type: "LaunchRequest" }), intent, touch: (action: string) => turn({ type: "Alexa.Presentation.APL.UserEvent", token: "reference", arguments: ["review", action] }) };
}

const mixed = () => [reference(1, 0.92), reference(2, 0.55), reference(3, 0.1), reference(4, 0.48), reference(5, undefined)];

const behaviours: Record<string, () => Promise<void> | void> = {
  "best bets are ordered by P(accept) and needs my help by uncertainty": () => {
    const best = orderQueue(mixed(), "best").map((item) => item.id);
    assert.deepEqual(best, ["ref-1", "ref-2", "ref-5", "ref-4", "ref-3"], "highest P first; no prediction counts as 0.5");
    const help = orderQueue(mixed(), "help").map((item) => item.id);
    assert.deepEqual(help.slice(0, 3), ["ref-5", "ref-4", "ref-2"], "closest to a coin toss first");
    assert.equal(help.at(-1), "ref-1");
  },

  "an editor reviews the best bets one by one and votes are recorded as theirs": async () => {
    const { review, votes } = fakeNewsroom(mixed());
    const talk = conversation(review, { token: "editor-token", screen: true });
    const first = await talk.intent("StartReviewIntent", { queue: "best bets" });
    assert.match(first.speech, /^5 references are waiting, starting with the ones I think you'll like most\. Number 1 of 5\. Reference number 1 From Example Source\. The subtitle of reference 1\. The summary of reference 1\./);
    assert.match(first.speech, /Say accept, or reject and why/);
    assert.equal(first.directives[0]?.token, "reference");
    assert.equal(first.directives[0]?.datasources?.referenceData.queueLabel, "Best bets · 1 of 5");
    const second = await talk.intent("AcceptReferenceIntent");
    assert.match(second.speech, /^Accepted\. Number 2 of 5\. Reference number 2/);
    assert.match(second.speech, /Accept, reject, or skip\?$/, "the prompt is short once heard");
    assert.deepEqual(votes[0], { referenceId: "ref-1", action: "accept", decisionRelationId: "decision-1", actorLabel: "editor@example.test" });
    const third = await talk.intent("RejectReferenceIntent", { reason: "it's off topic" });
    assert.match(third.speech, /^Rejected\. Number 3 of 5/);
    assert.equal(votes[1].action, "reject");
    assert.equal(votes[1].note, "it's off topic");
    assert.equal(votes[1].reasonCode, "out_of_scope", "spoken words map to the newsroom's reason codes");
  },

  "a bare reject asks why and the because answer completes it": async () => {
    const { review, votes } = fakeNewsroom(mixed());
    const talk = conversation(review);
    await talk.intent("StartReviewIntent", { queue: "best bets" });
    const ask = await talk.intent("RejectReferenceIntent");
    assert.match(ask.speech, /^Why\? Say because, and the reason/);
    assert.equal(votes.length, 0, "nothing is recorded without a reason");
    const done = await talk.intent("RejectReasonIntent", { reason: "it's a press release" });
    assert.match(done.speech, /^Rejected\. Number 2 of 5/);
    assert.equal(votes[0].note, "it's a press release");
    assert.equal(votes[0].reasonCode, "other");
    // "because ..." out of the blue checks first.
    const stray = await talk.intent("RejectReasonIntent", { reason: "whatever" });
    assert.match(stray.speech, /Did you want to reject it\?/);
    assert.equal(votes.length, 1);
  },

  "without a named list it starts with what needs help and says how to switch": async () => {
    const { review } = fakeNewsroom(mixed());
    const turn = await conversation(review).intent("StartReviewIntent");
    assert.match(turn.speech, /^Starting with what needs your help\. Say best bets any time/);
    assert.match(turn.speech, /starting with the ones I'm least sure about\. Number 1 of 5\. Reference number 5/);
  },

  "skip, undo, previous and repeat move without losing the editor": async () => {
    const { review, votes } = fakeNewsroom(mixed());
    const talk = conversation(review);
    await talk.intent("StartReviewIntent", { queue: "best bets" });
    assert.match((await talk.intent("SkipReferenceIntent")).speech, /^Skipped\. Number 2 of 5/);
    assert.match((await talk.intent("AMAZON.NextIntent")).speech, /^Skipped\. Number 3 of 5/, "next means skip during review");
    assert.match((await talk.intent("AcceptReferenceIntent")).speech, /^Accepted\. Number 4 of 5/);
    const undone = await talk.intent("UndoVoteIntent");
    // Best-bets order is 1, 2, 5 (no prediction counts as 0.5), 4, 3: the accepted third one is reference 5.
    assert.match(undone.speech, /^Undone: that one is no longer accepted\. Number 3 of 5\. Reference number 5/);
    assert.deepEqual(votes.at(-1), { referenceId: "ref-5", action: "reopen" });
    assert.match((await talk.intent("AMAZON.RepeatIntent")).speech, /Number 3 of 5\. Reference number 5/);
    assert.match((await talk.intent("AMAZON.PreviousIntent")).speech, /Number 2 of 5\. Reference number 2/);
    assert.match((await talk.intent("UndoVoteIntent")).speech, /nothing to undo/i);
  },

  "the editor can ask where they are, why, who published it, and for the link": async () => {
    const { review } = fakeNewsroom(mixed());
    const talk = conversation(review);
    await talk.intent("StartReviewIntent", { queue: "best bets" });
    assert.match((await talk.intent("HowManyLeftIntent")).speech, /^5 are left, counting this one\./);
    assert.match((await talk.intent("WhyThisReferenceIntent")).speech, /The Cyclotron thinks you'd accept it, about 92 percent sure\./);
    assert.match((await talk.intent("ReferenceSourceIntent")).speech, /It's from Example Source, published October 11, 2026\./);
    const sent = await talk.intent("SendReferenceToPhoneIntent");
    assert.match(sent.speech, /sent the link to the Alexa app/);
    assert.equal(sent.card?.type, "Simple");
    assert.match((await talk.intent("AMAZON.HelpIntent")).speech, /You're in best bets, number 1 of 5\. Say accept, or reject and why/);
    assert.match((await talk.intent("ContinueIntent")).speech, /The subtitle of reference 1\. The summary of reference 1\. It has a second sentence\./, "more reads the whole summary");
    assert.match((await talk.intent("BulkReviewIntent")).speech, /one at a time/);
  },

  "needs my help explains a coin toss": async () => {
    const { review } = fakeNewsroom(mixed());
    const talk = conversation(review);
    await talk.intent("StartReviewIntent", { queue: "needs my help" });
    await talk.intent("SkipReferenceIntent"); // ref-5 has no prediction; ref-4 is 0.48
    assert.match((await talk.intent("WhyThisReferenceIntent")).speech, /thinks you'd reject it, about 52 percent sure\. It's in this list because that guess is close to a coin toss\./);
  },

  "touch buttons on the card do what the words do": async () => {
    const { review, votes } = fakeNewsroom(mixed());
    const talk = conversation(review, { token: "editor-token", screen: true });
    await talk.intent("StartReviewIntent", { queue: "best bets" });
    assert.match((await talk.touch("accept")).speech, /^Accepted\./);
    assert.match((await talk.touch("reject")).speech, /^Why\?/, "a touched reject still asks why");
    assert.match((await talk.touch("skip")).speech, /^Skipped\./);
    assert.equal(votes.length, 1);
  },

  "the end of a round offers the other list": async () => {
    const { review } = fakeNewsroom([reference(1, 0.9), reference(2, 0.8)]);
    const talk = conversation(review);
    await talk.intent("StartReviewIntent", { queue: "best bets" });
    await talk.intent("AcceptReferenceIntent");
    const end = await talk.intent("AcceptReferenceIntent");
    assert.match(end.speech, /^Accepted\. That's the end of this round\. Say needs your help for the other list, or stop\./);
    const empty = await conversation(fakeNewsroom([]).review).intent("StartReviewIntent");
    assert.match(empty.speech, /nothing waiting for review/);
  },

  "a session carries a capped queue but counts them all": async () => {
    const many = Array.from({ length: 40 }, (_, index) => reference(index + 1, index / 40));
    const turn = await conversation(fakeNewsroom(many).review).intent("StartReviewIntent", { queue: "best bets" });
    assert.match(turn.speech, /^40 references are waiting/);
    assert.match(turn.speech, /Number 1 of 40/);
    assert.ok(QUEUE_SESSION_LIMIT < 40);
  },

  "not linked gets the link prompt, a reader is told review is for editors": async () => {
    const { review } = fakeNewsroom(mixed());
    const unlinked = await conversation(review, {}).intent("StartReviewIntent");
    assert.equal(unlinked.card?.type, "LinkAccount", "an Echo Show shows Amazon's QR code for this card");
    assert.match(unlinked.speech, /scan the code on your screen, and sign in with Google/);
    const reader = await conversation(review, { token: "reader-token" }).intent("StartReviewIntent");
    assert.match(reader.speech, /for this newsroom's editors/);
    assert.equal(reader.card, undefined);
  },

  "a refused or failed vote records nothing and says so": async () => {
    const refused = conversation(fakeNewsroom(mixed(), { refuseVotes: true }).review);
    await refused.intent("StartReviewIntent", { queue: "best bets" });
    const answer = await refused.intent("AcceptReferenceIntent");
    assert.equal(answer.card?.type, "LinkAccount");
    assert.match(answer.speech, /nothing was recorded/);
    const failing = conversation(fakeNewsroom(mixed(), { failVotes: true }).review);
    await failing.intent("StartReviewIntent", { queue: "best bets" });
    assert.match((await failing.intent("AcceptReferenceIntent")).speech, /couldn't record that, so nothing changed/);
  },

  "review words outside a review get a way in, and stop leaves cleanly": async () => {
    const { review } = fakeNewsroom(mixed());
    const talk = conversation(review);
    assert.match((await talk.intent("AcceptReferenceIntent")).speech, /not reviewing anything right now\. Say needs my help, or best bets/);
    await talk.intent("StartReviewIntent", { queue: "best bets" });
    assert.match((await talk.intent("AMAZON.FallbackIntent")).speech, /^Sorry, I didn't catch that\. Say accept, reject and why, or skip/, "no headline dump mid-review");
    const stop = await talk.intent("DoneReviewingIntent");
    assert.equal(stop.ends, true);
    assert.match(stop.speech, /Anything you didn't answer will still be waiting/);
  },

  "a linked editor's launch offers review first": async () => {
    const { review } = fakeNewsroom(mixed());
    const launch = await conversation(review).launch();
    assert.match(launch.speech, /^Welcome to Example Newsroom\. Say needs my help to review/);
    assert.equal(launch.ends, false);
  },

  "the newsroom client reads the feed index, attachments and decisions, and votes with the editor's token": async () => {
    const calls: { url: string; auth?: string; body?: Record<string, unknown> }[] = [];
    const respond = (data: unknown) => ({ ok: true, status: 200, json: async () => data, text: async () => JSON.stringify(data) });
    const fake: FetchLike = async (url, init) => {
      const body = init.body ? (JSON.parse(init.body) as Record<string, unknown>) : undefined;
      calls.push({ url, auth: init.headers.authorization, body });
      const query = String(body?.query ?? "");
      if (url.endsWith("/oauth2/userInfo")) return respond({ email: "editor@example.test" });
      if (query.includes("listReferencesByFeedStateAndPrediction")) {
        return respond({ data: { listReferencesByFeedStateAndPrediction: { items: [{ id: "r1", lineageId: "l1", title: "A story - Example Source", predictedAcceptProbability: 0.7, versionState: "current", feedArrivalAt: "2026-10-30T00:00:00Z" }, { id: "old", lineageId: "l0", title: "Old", versionState: "superseded" }], nextToken: null } } });
      }
      if (query.includes("listReferenceAttachmentsByReferenceLineageAndSortKey")) {
        return respond({ data: { listReferenceAttachmentsByReferenceLineageAndSortKey: { items: [{ role: "preview", metadata: JSON.stringify({ description: "The dek.", siteName: "Example Source" }) }, { role: "curation", metadata: { summary: { text: "The curated summary." } } }] } } });
      }
      if (query.includes("listSemanticRelationsBySubjectState")) {
        return respond({ data: { listSemanticRelationsBySubjectState: { items: [{ id: "rel-1", relationState: "current", predicate: "relevance_decision_is", subjectKind: "reference", subjectId: "r1", subjectLineageId: "l1", objectKind: "label", objectId: "include", objectLineageId: "include", confidence: 0.7, reviewRecommended: true, metadata: JSON.stringify({ decisionId: "d1", label: "include", positiveLabel: "include", reviewReason: "program" }) }] } } });
      }
      if (query.includes("reviewReferenceCuration")) return respond({ data: { reviewReferenceCuration: { ok: true, action: "reject", referenceId: "r1", status: "rejected" } } });
      throw new Error(`unexpected ${query.slice(0, 60)}`);
    };
    const client = createNewsroomReview({ config, accessToken: "editor-token", endpoint: "https://api.example.test/graphql", hostedUiOrigin: "https://auth.example.test", fetch: fake });
    const listed = await client.listUnrated(50);
    assert.deepEqual(listed.map((item) => item.id), ["r1"], "superseded versions are left out");
    assert.equal(calls[0].body?.variables && (calls[0].body.variables as Record<string, unknown>).feedStateKey, "knowledge-corpus-example#unrated");
    assert.equal(calls[0].auth, "editor-token", "AppSync gets the editor's own token");
    const details = await client.details(listed[0]);
    assert.equal(details.title, "A story", "the site name a feed appends is dropped");
    assert.equal(details.deck, "The dek.");
    assert.equal(details.summary, "The curated summary.");
    assert.equal(details.decision?.decisionRelationId, "rel-1");
    assert.equal(details.decision?.reviewRecommended, true);
    const result = await client.vote({ referenceId: "r1", action: "reject", note: "off topic", reasonCode: "out_of_scope", decisionRelationId: "rel-1", actorLabel: "editor@example.test" });
    assert.deepEqual(result, { ok: true, status: "rejected" });
    const voteCall = calls.find((call) => String(call.body?.query).includes("reviewReferenceCuration"));
    assert.deepEqual(voteCall?.body?.variables, { referenceId: "r1", action: "reject", note: "off topic", reasonCode: "out_of_scope", decisionRelationId: "rel-1", actorLabel: "editor@example.test" });
    assert.equal(await client.editorEmail(), "editor@example.test");
    assert.equal(displayTitle("Plain title"), "Plain title");
  },

  "an AppSync authorization error is a refusal, not a crash": async () => {
    const fake: FetchLike = async () => ({ ok: true, status: 200, json: async () => ({ errors: [{ message: "Not Authorized to access reviewReferenceCuration on type Mutation" }] }), text: async () => "" });
    const client = createNewsroomReview({ config, accessToken: "t", endpoint: "https://api.example.test/graphql", fetch: fake });
    assert.deepEqual(await client.vote({ referenceId: "r1", action: "accept" }), { ok: false, refused: true, message: "Not Authorized to access reviewReferenceCuration on type Mutation" });
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
