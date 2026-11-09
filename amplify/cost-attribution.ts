import { Aspects, Aws, CfnResource, Stack, TagManager, Token, type IAspect } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import type { IConstruct } from "constructs";
import { costTags, COSTED_RESOURCE_TYPES } from "./vendor/anthus-cost-accounting/tags";
import { applyCostTags, OWNER, type CostTagConfiguration } from "./vendor/anthus-cost-accounting/cdk";

/**
 * Prospectus cost accounting in a site's Amplify backend (Prospectus docs/COST_ACCOUNTING.md).
 *
 * Every resource is tagged account `owner`, app `papyrus` and the site ID as the deployment; Prospectus finds the
 * owning Account from the papyrus-<site> entitlement. The site ID comes from the Amplify branch variable
 * `PAPYRUS_SITE_ID`, which the app-shell stack sets (infra/amplify-app-shell/lib/cost-attribution.ts). A build
 * without it fails the synth: an untagged backend would be charged to nobody.
 */

const SITE_ID = /^[a-z0-9][a-z0-9-]{0,62}$/;
/** The Prospectus usage queues live in us-east-1 (the package's PROSPECTUS_REGION). */
export const PROSPECTUS_USAGE_REGION = "us-east-1";

export type SiteCostAttribution = CostTagConfiguration & { deployment: string };

export function siteCostAttribution(env: Record<string, string | undefined> = process.env): SiteCostAttribution {
  const siteId = env.PAPYRUS_SITE_ID?.trim() ?? "";
  if (!siteId) {
    throw new Error(
      "The site backend needs PAPYRUS_SITE_ID to tag its resources for cost accounting (anthus:deployment). The app-shell " +
        "stack sets it as an Amplify branch variable; for a sandbox, export it. Refusing to synthesize an untagged backend.",
    );
  }
  if (!SITE_ID.test(siteId)) throw new Error("PAPYRUS_SITE_ID must be lower-case letters, digits and hyphens.");
  return { account: OWNER, app: "papyrus", deployment: siteId };
}

/** Tags every resource in the backend (all nested stacks) with the site's cost attribution. */
export function applySiteBackendCostTags(scope: IConstruct, attribution: SiteCostAttribution): void {
  applyCostTags(scope, attribution);
  Aspects.of(scope).add(new TagUntaggableCostedResources(costTags(attribution)));
}

/**
 * The Tags aspect reaches only constructs with a TagManager. CDK writes some costed resources as raw CfnResources
 * (the custom-resource provider Lambda behind `autoDeleteObjects`, for one), so their tags are written directly.
 */
class TagUntaggableCostedResources implements IAspect {
  constructor(private readonly tags: Record<string, string>) {}

  visit(node: IConstruct): void {
    if (!CfnResource.isCfnResource(node) || TagManager.isTaggable(node)) return;
    if (!(COSTED_RESOURCE_TYPES as readonly string[]).includes(node.cfnResourceType)) return;
    node.addPropertyOverride("Tags", Object.entries(this.tags).map(([Key, Value]) => ({ Key, Value })));
  }
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
