import type { AlexaWiringStep } from "../contracts";
import { GRAPHQL_ENDPOINT_ENVIRONMENT_VARIABLE } from "../review/newsroom";

/**
 * With account linking on, the skill reads and votes in the newsroom under the linked editor's own token, so it needs the site's
 * AppSync endpoint. No IAM grant: the skill never calls AppSync with its own role (docs/alexa.md, "Reviewing references").
 */
export const alexaGraphqlEndpointStep: AlexaWiringStep = (_backend, config, context, lambda) => {
  if (!config.accountLinking) return;
  lambda.addEnvironment(GRAPHQL_ENDPOINT_ENVIRONMENT_VARIABLE, context.graphqlEndpoint);
};
