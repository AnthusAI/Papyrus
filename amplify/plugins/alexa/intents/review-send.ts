import { reviewIntent } from "../review/intent";
import { sendToPhone } from "../review/flow";

/** "Send it to my phone": a card in the Alexa app with the title and the source link. */
export const reviewSendIntent = reviewIntent({
  id: "review-send",
  name: "SendReferenceToPhoneIntent",
  samples: ["send it to my phone", "send this to my phone", "send me the link", "send me this one", "send it to me", "open it on my phone", "save it to my phone", "give me the link", "I want to read it", "let me read it", "show it on my phone"],
  handle: (handlerInput, dependencies) => sendToPhone(handlerInput, dependencies),
});
