import type { VerifyAuthChallengeResponseTriggerHandler } from "aws-lambda";

export const handler: VerifyAuthChallengeResponseTriggerHandler = async (event) => {
  event.response.answerCorrect = event.request.challengeAnswer === process.env.SPIKE_SECRET;
  return event;
};
