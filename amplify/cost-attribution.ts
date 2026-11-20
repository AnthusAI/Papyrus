import { Aws, Stack, Token } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { applyCostTagWaves, costTagWave } from "./cost-tag-waves";
import { costTags } from "./vendor/anthus-cost-accounting/tags";
import { OWNER, type CostTagConfiguration } from "./vendor/anthus-cost-accounting/cdk";
import { isReservedDeployment, type SharedTierPlan } from "./shared-stack/names";
import { SHARED } from "./vendor/anthus-cost-accounting/tags";

/**
 * Prospectus cost accounting in a site's Amplify backend (Prospectus docs/COST_ACCOUNTING.md).
 *
 * Every resource is tagged account `owner`, app `papyrus` and the site ID as the deployment; Prospectus finds the
 * owning Account from the papyrus-<site> entitlement. The tags arrive in waves (amplify/cost-tag-waves.ts), because
 * tagging a whole backend at once is more than CloudFormation takes in one operation (Papyrus 5.99.0 rolled Machines on
 * Machines back). `papyrus-infra backend-deploy` sets PAPYRUS_COST_TAG_WAVE for each pass; a build that runs
 * `ampx pipeline-deploy` directly sets nothing and gets exactly the backend it had before cost accounting: no tags, no
 * usage environment, no new IAM statements.
 *
 * The site ID is the `siteId` of the site's own infra/site.json (the build runs at the site repository's root), so no
 * branch variable has to be set. A PAPYRUS_SITE_ID in the environment is used where there is no site.json (a sandbox,
 * the engine's own synth) and must agree with it where there is one.
 */

const SITE_ID = /^[a-z0-9][a-z0-9-]{0,62}$/;
/** The Prospectus usage queues live in us-east-1 (the package's PROSPECTUS_REGION). */
export const PROSPECTUS_USAGE_REGION = "us-east-1";

export type SiteCostAttribution = CostTagConfiguration & { deployment: string; wave: number };

/** The `siteId` of the site.json under `root`, or undefined when there is none. */
export function siteIdFromSiteJson(root: string): string | undefined {
  const file = path.join(root, "infra", "site.json");
  if (!existsSync(file)) return undefined;
  const siteId = (JSON.parse(readFileSync(file, "utf8")) as { siteId?: unknown }).siteId;
  if (typeof siteId !== "string" || !siteId.trim()) throw new Error(`${file} has no siteId.`);
  return siteId.trim();
}

/** The site's cost attribution, or null when the build did not ask for a cost tag wave. */
export function siteCostAttribution(env: Record<string, string | undefined> = process.env, root = process.cwd()): SiteCostAttribution | null {
  const wave = costTagWave(env);
  if (wave === null) return null;
  const fromSiteJson = siteIdFromSiteJson(root);
  const fromEnvironment = env.PAPYRUS_SITE_ID?.trim() || undefined;
  if (fromSiteJson && fromEnvironment && fromSiteJson !== fromEnvironment) {
    throw new Error(`PAPYRUS_SITE_ID is ${fromEnvironment} but infra/site.json says ${fromSiteJson}; they name the same site.`);
  }
  const siteId = fromSiteJson ?? fromEnvironment;
  if (!siteId) {
    throw new Error(
      "The site backend needs its site ID to tag its resources for cost accounting (anthus:deployment): the siteId of " +
        "infra/site.json, or PAPYRUS_SITE_ID where there is no site.json. Refusing to synthesize an untagged backend.",
    );
  }
  if (!SITE_ID.test(siteId)) throw new Error("The site ID must be lower-case letters, digits and hyphens.");
  if (isReservedDeployment(siteId)) throw new Error(`The site ID ${siteId} is a deployment value of the shared tier (shared, shared-prod, shared-staging); a dedicated site cannot use it.`);
  return { account: OWNER, app: "papyrus", deployment: siteId, wave };
}

/**
 * A shared stack's cost attribution: account `shared` (Prospectus splits the cost by each tenant's reported usage) and the
 * tier's own deployment value, so each stack has its own line in Cost Explorer and its own budget. Always every wave: a
 * shared stack is created fresh by the pipeline, so there is no earlier release to split the tagging across.
 */
export function sharedStackCostAttribution(plan: SharedTierPlan): SiteCostAttribution {
  return { account: SHARED, app: "papyrus", deployment: plan.deployment, wave: Number.POSITIVE_INFINITY };
}

/**
 * Tags the backend's resources, in every nested stack, up to the build's wave. `first` names stacks that change in
 * the first pass anyway (the usage senders'), so their tags arrive in the same operation.
 */
export function applySiteBackendCostTags(scope: Stack, attribution: SiteCostAttribution, first: Stack[] = []): void {
  const { wave, ...configuration } = attribution;
  applyCostTagWaves(scope, costTags(configuration), wave, first);
}

/** The Prospectus product a dedicated site sends usage as. The shared tier will send as `papyrus` (kanbus-f45f7f; not built). */
export const siteUsageProduct = (attribution: SiteCostAttribution) => `papyrus-${attribution.deployment}`;

/**
 * The product's usage queue URL, the same as the package's `usageQueueUrl(product, account)`. The Prospectus account
 * is the stack's own account (papyrus-production hosts both), taken from the stack environment, never a literal; in
 * an Amplify build it is a deploy-time token, which `usageQueueUrl` cannot take, so the URL is built in its format.
 */
export function usageQueueUrlFor(stack: Stack, product: string): string {
  const account = Token.isUnresolved(stack.account) ? Aws.ACCOUNT_ID : stack.account;
  return `https://sqs.${PROSPECTUS_USAGE_REGION}.amazonaws.com/${account}/prospectus-usage-${product}`;
}

export function usageQueueArnFor(stack: Stack, product: string): string {
  const account = Token.isUnresolved(stack.account) ? Aws.ACCOUNT_ID : stack.account;
  return `arn:${Aws.PARTITION}:sqs:${PROSPECTUS_USAGE_REGION}:${account}:prospectus-usage-${product}`;
}

/**
 * Lets a function report usage: the environment the Python sender reads (papyrus_cost_usage.SiteUsage) and
 * `sqs:SendMessage` on its site's own queue only. The queue's policy in Prospectus must also list the function's
 * role (Prospectus accounts/papyrus-sites.json); until it does, sends are refused there and retried.
 */
export function wireSiteUsageSender(lambda: LambdaFunction, attribution: SiteCostAttribution): void {
  const stack = Stack.of(lambda);
  const product = siteUsageProduct(attribution);
  lambda.addEnvironment("PROSPECTUS_USAGE_QUEUE_URL", usageQueueUrlFor(stack, product));
  lambda.addEnvironment("PAPYRUS_SITE_ID", attribution.deployment);
  lambda.addToRolePolicy(
    new PolicyStatement({
      sid: "SendUsageToOwnProspectusQueue",
      effect: Effect.ALLOW,
      actions: ["sqs:SendMessage"],
      resources: [usageQueueArnFor(stack, product)],
    }),
  );
}
