import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";

/**
 * The model key of a site's agent runs (PPY-8a374e, note on PPY-6af46b).
 *
 * A change feed (`item-change-feed.ts`, `change-feeds.ts`) puts one wake on the site's wake queue for each agent that listens for a change, and the wake
 * carries `openaiKeyParameter`, the NAME of the SSM parameter the run reads its model key from (`item_change_feed.Site`, `procedure_runner.validate_request`).
 * The runner (the shared `papyrus-procedure-runner` Lambda, `infra/procedures/papyrus-procedure-runner.yaml`) is the one that reads the parameter, with its own role:
 * a feed never reads, prints or stores the key, and holds no right to it. With no name set, a feed's wakes carry none and the run fails closed with
 * `The run has no model key`: there is no fallback key.
 *
 * The name is a site setting, `agents.openAiKeyParameter` in the site's backend configuration (`PapyrusAgentsConfig`). A name is not a secret.
 */
export const MODEL_KEY_PARAMETER_ENV = "PAPYRUS_OPENAI_KEY_PARAMETER";

/** Names the model key's SSM parameter on a feed function, when the site sets one. Adds no resource and no permission. */
export function setModelKeyParameter(feed: LambdaFunction, parameterName: string | undefined): void {
  if (parameterName !== undefined) feed.addEnvironment(MODEL_KEY_PARAMETER_ENV, parameterName);
}
