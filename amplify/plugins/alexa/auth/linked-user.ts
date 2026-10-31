import type { HandlerInput } from "ask-sdk-core";
import type { Response } from "ask-sdk-model";
import type { AccessTokenVerifier } from "../contracts";

export type LinkedUser = { sub: string; username: string; email?: string; groups: string[] };

export const LINK_ACCOUNT_SPEECH =
  "To get your own feed, open the Alexa app or scan the code on your screen to link your account.";

/** The signed-in user behind this request, or null when no linked account token is present or it does not verify. */
export async function linkedUser(handlerInput: HandlerInput, verifier: AccessTokenVerifier | undefined): Promise<LinkedUser | null> {
  const accessToken = handlerInput.requestEnvelope.context?.System?.user?.accessToken;
  if (!accessToken || !verifier) return null;
  const result = await verifier.verify(accessToken);
  if (!result.ok) return null;
  const { claims } = result.token;
  const groups = Array.isArray(claims["cognito:groups"]) ? claims["cognito:groups"].filter((g): g is string => typeof g === "string") : [];
  const username = typeof claims.username === "string" ? claims.username : typeof claims["cognito:username"] === "string" ? claims["cognito:username"] : result.token.subject;
  const user: LinkedUser = { sub: result.token.subject, username, groups };
  if (typeof claims.email === "string") user.email = claims.email;
  return user;
}

/** Speech plus a LinkAccount card; the session stays open so the caller can offer public content next. */
export function linkAccountResponse(handlerInput: HandlerInput, speech: string = LINK_ACCOUNT_SPEECH): Response {
  return handlerInput.responseBuilder.speak(speech).withLinkAccountCard().getResponse();
}

/** For signed-in intents: run `signedIn` with the user, or answer with the LinkAccount card. */
export async function requireLinkedUser(
  handlerInput: HandlerInput,
  verifier: AccessTokenVerifier | undefined,
  signedIn: (user: LinkedUser) => Response | Promise<Response>,
  speech?: string,
): Promise<Response> {
  const user = await linkedUser(handlerInput, verifier);
  return user ? signedIn(user) : linkAccountResponse(handlerInput, speech);
}
