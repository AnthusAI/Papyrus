import type { IntentModule } from "../contracts";
import { REVIEW_EVENT_ARGUMENT } from "../apl/reference";
import { skip, vote } from "../review/flow";
import { APL_USER_EVENT_REQUEST } from "./apl-user-event";

/** A touched Accept / Reject / Skip button on the reference card: the same as saying it (Reject still asks why). */
export const reviewTouchIntent: IntentModule = {
  id: "review-touch",
  create: (dependencies) => ({
    canHandle: (handlerInput) => {
      const request = handlerInput.requestEnvelope.request as { type: string; arguments?: unknown[] };
      return request.type === APL_USER_EVENT_REQUEST && request.arguments?.[0] === REVIEW_EVENT_ARGUMENT;
    },
    handle: (handlerInput) => {
      const action = (handlerInput.requestEnvelope.request as { arguments?: unknown[] }).arguments?.[1];
      if (action === "accept" || action === "reject") return vote(handlerInput, dependencies, action);
      return skip(handlerInput, dependencies);
    },
  }),
};
