/**
 * Names and statements of the shared tier's isolation layers (PPY-daf673, docs/shared-stack.md,
 * docs/plans/multi-tenant-architecture.md "Isolation inside an existing account").
 *
 * Pure: no CDK imports, so the app shell and the tests can read the same facts. The app shell's package keeps a copy of the
 * deny (infra/amplify-app-shell/lib/shared-stack-deny.ts) because it ships separately; scripts/test-shared-stack.ts fails
 * when the two differ.
 */

export type SharedTier = "production" | "staging";
export const SHARED_TIERS: readonly SharedTier[] = ["production", "staging"];

/** Every name the shared tier owns starts with this. No dedicated site's stack or resource does. */
export const SHARED_FAMILY_PREFIX = "papyrus-shared-";

/** The cost tag that names a deployment (amplify/vendor/anthus-cost-accounting/tags.ts: TAG_DEPLOYMENT). */
export const SHARED_DEPLOYMENT_TAG_KEY = "anthus:deployment";

export type SharedTierPlan = {
  tier: SharedTier;
  /** The prefix of the tier's stacks, roles, policy, key alias, functions and buckets. Neither tier's prefix starts with the other's. */
  stackPrefix: string;
  /** The `anthus:deployment` value every resource of the tier carries. */
  deployment: string;
  /** The pipeline-made stack that holds the key, the permissions boundary and the budget. */
  foundationStackName: string;
  /** Every role the tier's backend creates sits on this IAM path; the key policy and the boundary read it. */
  rolePath: string;
  keyAlias: string;
  boundaryPolicyName: string;
  /** SSM String parameters the foundation stack writes, read by the backend at deploy time. */
  keyArnParameter: string;
  ssmPrefix: string;
};

const PLANS: Record<SharedTier, SharedTierPlan> = {
  production: plan("production", "papyrus-shared-prod", "shared-prod", "prod"),
  staging: plan("staging", "papyrus-shared-staging", "shared-staging", "staging"),
};

function plan(tier: SharedTier, stackPrefix: string, deployment: string, ssmName: string): SharedTierPlan {
  return {
    tier,
    stackPrefix,
    deployment,
    foundationStackName: `${stackPrefix}-foundation`,
    rolePath: `/${stackPrefix}/`,
    keyAlias: `alias/${stackPrefix}`,
    boundaryPolicyName: `${stackPrefix}-boundary`,
    keyArnParameter: `/papyrus/shared/${ssmName}/kms-key-arn`,
    ssmPrefix: `/papyrus/shared/${ssmName}`,
  };
}

export function sharedTierPlan(tier: SharedTier): SharedTierPlan {
  return PLANS[tier];
}

export function isSharedTier(value: unknown): value is SharedTier {
  return value === "production" || value === "staging";
}

/** Both tiers' `anthus:deployment` values; the deny on dedicated roles names exactly these. */
export const SHARED_DEPLOYMENT_VALUES: readonly string[] = SHARED_TIERS.map((tier) => PLANS[tier].deployment);

/**
 * A dedicated site's id is its `anthus:deployment` value, so it must never equal a shared value (a site named
 * `shared-prod` would be denied its own resources and would be billed as the shared tier). `shared` alone is reserved too:
 * the design note and the cost key `shared/papyrus/` use it for the account value.
 */
export function isReservedDeployment(siteId: string): boolean {
  return siteId === "shared" || SHARED_DEPLOYMENT_VALUES.includes(siteId);
}

export type IamStatement = {
  Sid: string;
  Effect: "Allow" | "Deny";
  Action: string[];
  Resource: string[];
  Condition?: Record<string, Record<string, string | string[]>>;
};

/** The name of the inline policy that carries the deny on a dedicated role. */
export const SHARED_DENY_POLICY_NAME = "papyrus-deny-shared-stack";

/**
 * What a dedicated site's role may never touch: any resource that carries a shared `anthus:deployment` tag, and any
 * resource named with the shared prefix. Both are needed: a tag condition is evaluated only for services and actions that
 * support it, and a name pattern needs the resource to be named. Roles that the shared tier's own pipeline and operator use
 * are not dedicated roles and do not carry this.
 */
export function sharedStackDenyStatements(): IamStatement[] {
  return [
    {
      Sid: "DenyTaggedSharedStackResources",
      Effect: "Deny",
      Action: ["*"],
      Resource: ["*"],
      Condition: { StringEquals: { [`aws:ResourceTag/${SHARED_DEPLOYMENT_TAG_KEY}`]: [...SHARED_DEPLOYMENT_VALUES] } },
    },
    {
      Sid: "DenyNamedSharedStackResources",
      Effect: "Deny",
      Action: ["*"],
      Resource: [
        `arn:aws:cloudformation:*:*:stack/${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:s3:::${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:s3:::${SHARED_FAMILY_PREFIX}*/*`,
        `arn:aws:lambda:*:*:function:${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:logs:*:*:log-group:/aws/lambda/${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:logs:*:*:log-group:/aws/lambda/${SHARED_FAMILY_PREFIX}*:*`,
        `arn:aws:iam::*:role/${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:iam::*:policy/${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:ssm:*:*:parameter/papyrus/shared/*`,
        `arn:aws:sns:*:*:${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:sqs:*:*:${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:cloudwatch:*:*:alarm:${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:kms:*:*:alias/${SHARED_FAMILY_PREFIX}*`,
      ],
    },
    {
      Sid: "DenySharedStackKeys",
      Effect: "Deny",
      Action: ["kms:*"],
      Resource: ["*"],
      Condition: { "ForAnyValue:StringLike": { "kms:ResourceAliases": `alias/${SHARED_FAMILY_PREFIX}*` } },
    },
  ];
}

export function sharedStackDenyPolicyDocument(): { Version: string; Statement: IamStatement[] } {
  return { Version: "2012-10-17", Statement: sharedStackDenyStatements() };
}
