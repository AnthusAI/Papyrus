import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";

/** How a site asks for a plugin in `papyrus.config.ts`: `plugins: ["signup"]` or `plugins: [{ name: "signup", forms: ["news"] }]`. */
export type PluginRequest = string | ({ name: string } & Record<string, unknown>);

/** What a plugin declares about itself. A test pins the schema, the guest rules and the static files to this. */
export type PluginManifest = {
  name: string;
  /** Public contract version. Bump it when a mutation input, a model field, an element name or an attribute changes. No compatibility shims. */
  contract: number;
  models: string[];
  mutations: string[];
  /** What an anonymous visitor may call. Everything else is closed to guests. */
  guest: { mutations: string[] };
  newsroomPanels: { id: string; label: string }[];
  /** Keys the projector writes into the site bucket when the plugin is enabled. */
  staticAssets: string[];
};

/** Where the deploy-time wiring puts its resources. Filled in by `defineSiteBackend`. */
export type PluginWiringContext = {
  createStack: (name: string) => Construct;
  graphqlApiId: string;
  graphqlEndpoint: string;
  /** The site's `content-actions` function: it runs the projection tasks a plugin may add (for example `reader-snapshot`). */
  contentActionsLambda: LambdaFunction;
};

export type PapyrusPlugin<Config, Functions = unknown> = {
  manifest: PluginManifest;
  /** Validates the request and fills in defaults. Throws a readable error. */
  resolveConfig: (request: PluginRequest) => Config;
  /** Amplify function resources the plugin adds to `defineBackend`. */
  functions: () => Functions;
  /** Models and custom operations merged into the site schema. */
  schemaDefinitions: () => Record<string, unknown>;
  /** The settings the newsroom and the page component may read from `amplify_outputs.json` (`custom.papyrusPlugins.<name>`). Never secrets. */
  publicSettings: (config: Config) => Record<string, unknown>;
  /** Everything that needs the backend to exist: IAM, environment, WAF, outputs. */
  wire: (backend: any, config: Config, context: PluginWiringContext) => void;
};
