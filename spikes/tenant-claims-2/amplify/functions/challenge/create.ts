import type { CreateAuthChallengeTriggerHandler } from "aws-lambda";

export const handler: CreateAuthChallengeTriggerHandler = async (event) => {
  event.response.publicChallengeParameters = { kind: "spike" };
  event.response.privateChallengeParameters = { answer: "spike" };
  return event;
};
