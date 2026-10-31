import type { RequestEnvelope } from "ask-sdk-model";

/** True when the device that sent the request can render APL. Voice-only devices (Echo Dot, phones without a screen) cannot. */
export function supportsApl(requestEnvelope: RequestEnvelope): boolean {
  const interfaces = requestEnvelope.context?.System?.device?.supportedInterfaces as Record<string, unknown> | undefined;
  const apl = interfaces?.["Alexa.Presentation.APL"];
  return typeof apl === "object" && apl !== null;
}
