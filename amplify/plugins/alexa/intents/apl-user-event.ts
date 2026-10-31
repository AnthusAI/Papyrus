import type { Response } from "ask-sdk-model";
import type { HandlerInput } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { OPEN_STORY_ARGUMENT } from "../apl/feed";

/**
 * Opens the story at `index` of the feed that was on screen. The intents task exports the real function (the one a voice request for
 * a story uses); after both tasks merge it is passed to `createAplUserEventIntent({ openStory })` in `intents/index.ts`.
 */
export type OpenStory = (handlerInput: HandlerInput, index: number) => Response | Promise<Response>;

/** The default until then: speech only, so a touch is acknowledged and nothing is rendered. */
export const speechOnlyOpenStory: OpenStory = (handlerInput, index) =>
  handlerInput.responseBuilder.speak(`Opening story ${index + 1}.`).withShouldEndSession(false).getResponse();

export const APL_USER_EVENT_REQUEST = "Alexa.Presentation.APL.UserEvent";

/** The story index a touched card sent (`["openStory", <index>]`), or undefined when the event is not that. */
export function tappedStoryIndex(requestArguments: unknown): number | undefined {
  if (!Array.isArray(requestArguments) || requestArguments[0] !== OPEN_STORY_ARGUMENT) return undefined;
  const index = Number(requestArguments[1]);
  return Number.isInteger(index) && index >= 0 ? index : undefined;
}

export function createAplUserEventIntent(options: { openStory?: OpenStory } = {}): IntentModule {
  const openStory = options.openStory ?? speechOnlyOpenStory;
  return {
    id: "apl-user-event",
    create: () => ({
      canHandle: (handlerInput) => handlerInput.requestEnvelope.request.type === APL_USER_EVENT_REQUEST,
      handle: async (handlerInput) => {
        const request = handlerInput.requestEnvelope.request as { arguments?: unknown[] };
        const index = tappedStoryIndex(request.arguments);
        if (index === undefined) return handlerInput.responseBuilder.speak("Sorry, I could not tell which story you touched.").withShouldEndSession(false).getResponse();
        return openStory(handlerInput, index);
      },
    }),
  };
}

export const aplUserEventIntent: IntentModule = createAplUserEventIntent();
