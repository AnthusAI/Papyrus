import { getSlotValue } from "ask-sdk-core";
import { reviewIntent } from "../review/intent";
import { asEditor, startQueue, type ReviewQueueKind } from "../review/flow";
import { sentence } from "../speech/ssml";

export const INTENT_NAME = "StartReviewIntent";
export const QUEUE_SLOT_TYPE = "REVIEW_QUEUE";

/** The queue a slot value names: its resolved id when Alexa matched a synonym, else the spoken words. Unnamed: needs my help. */
export function queueOf(handlerInput: Parameters<typeof getSlotValue>[0]): ReviewQueueKind | undefined {
  const slot = handlerInput.request.type === "IntentRequest" ? handlerInput.request.intent.slots?.queue : undefined;
  const resolved = slot?.resolutions?.resolutionsPerAuthority?.find((authority) => authority.status.code === "ER_SUCCESS_MATCH")?.values?.[0]?.value?.id;
  if (resolved === "best" || resolved === "help") return resolved;
  const spoken = (slot?.value ?? "").toLowerCase();
  if (/best|like|interest|top|good|pick/.test(spoken)) return "best";
  if (/help|need|unsure|sure|uncertain|hard|tricky/.test(spoken)) return "help";
  return undefined;
}

/**
 * "What needs my help", "review the best bets", "show me references": starts a review queue. Without a named queue it starts with
 * what needs help (the Cyclotron learns most from those) and says the other is a word away.
 */
export const reviewStartIntent = reviewIntent({
  id: "review-start",
  name: INTENT_NAME,
  samples: [
    "{queue}",
    "review {queue}",
    "let's review {queue}",
    "go through {queue}",
    "show me {queue}",
    "read me {queue}",
    "what {queue}",
    "start with {queue}",
    "switch to {queue}",
    "give me {queue}",
    "the {queue} list",
    "review references",
    "review the references",
    "review my references",
    "let's review",
    "start reviewing",
    "start a review",
    "references",
    "the references",
    "show me references",
    "show me the references",
    "show me recent references",
    "show me the latest references",
    "read me the references",
    "list the references",
    "list references",
    "recent references",
    "new references",
    "my references",
    "what references are waiting",
    "what references do I have",
    "any references",
    "go through the references",
    "curate",
    "let's curate",
    "triage",
  ],
  slots: [{ name: "queue", type: QUEUE_SLOT_TYPE }],
  types: [
    {
      name: QUEUE_SLOT_TYPE,
      values: [
        {
          id: "best",
          name: {
            value: "best bets",
            synonyms: ["best bet", "the best bets", "the best ones", "most interesting", "the most interesting ones", "what I'll like", "what I'd like", "the ones I'll like", "top picks", "the good ones", "the top ones", "your picks"],
          },
        },
        {
          id: "help",
          name: {
            value: "needs my help",
            synonyms: ["needs me", "need my help", "needs help", "the ones that need my help", "what needs my help", "least sure", "the ones you're unsure about", "unsure", "uncertain", "the hard ones", "the tricky ones"],
          },
        },
      ],
    },
  ],
  handle: (handlerInput, dependencies) =>
    asEditor(handlerInput, dependencies, (review) => {
      const named = queueOf(handlerInput.requestEnvelope);
      const kind = named ?? "help";
      const lead = named ? "" : sentence("Starting with what needs your help. Say best bets any time for the ones I think you'll like.");
      return startQueue(handlerInput, dependencies, review, kind, lead);
    }),
});
