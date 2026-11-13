import type { DefineAuthChallengeTriggerHandler } from "aws-lambda";

// Sandbox-only passwordless sign-in: no password is ever set; a deploy-time secret stands in for the Google round trip.
export const handler: DefineAuthChallengeTriggerHandler = async (event) => {
  const session = event.request.session;
  const last = session[session.length - 1];
  if (session.length === 0) {
    event.response = { challengeName: "CUSTOM_CHALLENGE", issueTokens: false, failAuthentication: false };
  } else if (last?.challengeResult === true) {
    event.response = { issueTokens: true, failAuthentication: false };
  } else {
    event.response = { issueTokens: false, failAuthentication: true };
  }
  return event;
};
