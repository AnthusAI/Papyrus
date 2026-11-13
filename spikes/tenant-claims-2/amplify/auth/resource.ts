import { defineAuth } from "@aws-amplify/backend";
import { createAuthChallenge, defineAuthChallenge, verifyAuthChallengeResponse } from "./functions";

export const auth = defineAuth({
  loginWith: { email: true },
  triggers: { defineAuthChallenge, createAuthChallenge, verifyAuthChallengeResponse },
});
