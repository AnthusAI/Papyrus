import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import type { ResolvedPlugin } from "./registry";

export const PLUGINS_ENVIRONMENT_VARIABLE = "PAPYRUS_PLUGINS";
export const PLUGINS_OUTPUT_KEY = "papyrusPlugins";

/**
 * Deploy-time wiring for every enabled plugin. A site without plugins reaches no line of this:
 * nothing is added to the stacks, the environment or the outputs.
 */
export function wirePlugins(backend: any, plugins: ResolvedPlugin[], contentActionsLambda: LambdaFunction): void {
  if (plugins.length === 0) return;
  const graphqlApi = backend.data.resources.graphqlApi;
  const context = {
    createStack: (name: string) => backend.createStack(name),
    graphqlApiId: graphqlApi.apiId as string,
    graphqlEndpoint: backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string,
    contentActionsLambda,
  };
  for (const { plugin, config } of plugins) plugin.wire(backend, config, context);
  contentActionsLambda.addEnvironment(PLUGINS_ENVIRONMENT_VARIABLE, plugins.map(({ plugin }) => plugin.manifest.name).join(","));
  backend.addOutput({
    custom: {
      [PLUGINS_OUTPUT_KEY]: Object.fromEntries(plugins.map(({ plugin, config }) => [plugin.manifest.name, plugin.publicSettings(config)])),
    },
  });
}
