import { Aws, CfnParameter, Fn, RemovalPolicy, Stack, Token } from "aws-cdk-lib";
import { CfnRole } from "aws-cdk-lib/aws-iam";
import { CfnLogGroup } from "aws-cdk-lib/aws-logs";
import { CfnBucket } from "aws-cdk-lib/aws-s3";
import { CfnIndex, CfnVectorBucket } from "aws-cdk-lib/aws-s3vectors";
import { CfnQueue } from "aws-cdk-lib/aws-sqs";
import { CfnTable } from "aws-cdk-lib/aws-dynamodb";
import { createHash } from "node:crypto";
import { appendInlinePolicy, appendInlinePolicyToRawRole, findAllOfType, findResourcesOfCfnType, functionOwnerId, isInfrastructureFunction } from "./inline-policy";
import type { SharedTierPlan } from "./names";
import type { SharedStackSettings } from "./settings";

/**
 * Layers 2 and 3 of the shared tier's isolation, applied to the backend `defineSiteBackend` built (docs/shared-stack.md):
 * the stack's own KMS key on everything that can take one, the permissions boundary and the role path on every role, names
 * that carry the stack's prefix, and reserved concurrency taken from `settings.ts`.
 *
 * The key and the boundary policy are made by the foundation stack (infra/shared-stack/papyrus-shared-foundation.yaml). The
 * backend learns the key's ARN from an SSM parameter at deploy time and the boundary's ARN from its name.
 */

export type SharedBackendHandle = {
  stack: Stack;
  data: { resources: { cfnResources: { amplifyDynamoDbTables: Record<string, { sseSpecification: unknown }> } } };
};

/** What the key could not be attached to, by resource type, because Amplify or the service gives no way to. */
export const RESOURCES_THAT_CANNOT_TAKE_THE_KEY = [
  {
    resource: "Amplify secrets (secret(\"GOOGLE_CLIENT_ID\") and the other secret() values)",
    reason: "Amplify Gen 2 stores them in SSM under /amplify/<app id>/ with the AWS-managed key and has no hook to choose another key.",
  },
  {
    resource: "SecureString parameters made by custom resources (plugins that write one, such as newsletter)",
    reason: "the shared stack runs no plugin that does; a plugin that is turned on later must be given the key by its custom resource handler.",
  },
  {
    resource: "CloudFront KeyValueStore of the projection publication",
    reason: "CloudFront key value stores have no KMS option; the store holds redirects only, no tenant content.",
  },
  {
    resource: "Cognito user pool",
    reason: "Cognito encrypts with AWS-owned keys and offers no customer-managed key.",
  },
  {
    resource: "AppSync API",
    reason: "AppSync encrypts at rest with AWS-owned keys and offers no customer-managed key; the data lives in the tables and bucket, which take the key.",
  },
  {
    resource: "Lambda environment variables and code",
    reason: "the Amplify function constructs expose no KMS key for them; the variables hold names and settings, no secrets.",
  },
] as const;

export function shortHash(value: string, length = 8): string {
  return createHash("sha256").update(value).digest("hex").slice(0, length);
}

function slug(value: string, max: number): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, max).replace(/-+$/g, "");
}

export function boundaryPolicyArn(plan: SharedTierPlan): string {
  return `arn:${Aws.PARTITION}:iam::${Aws.ACCOUNT_ID}:policy/${plan.boundaryPolicyName}`;
}

/** The statement a shared role needs to use the stack's key; the boundary also allows it, the key policy admits the role path. */
export function keyUseStatement(keyArn: string): object {
  return {
    Sid: "UseTheSharedStackKey",
    Effect: "Allow",
    Action: ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey", "kms:CreateGrant"],
    Resource: [keyArn],
  };
}

export type SharedIsolationReport = {
  keyArnParameter: string;
  roles: number;
  functions: number;
  reservedFunctions: string[];
  functionTargets: Array<{ functionName: string; reserved?: number }>;
  reservedTotal: number;
  buckets: number;
  queues: number;
  tables: number;
  logGroups: number;
  vectorResources: number;
};

export function applySharedStackIsolation(backend: SharedBackendHandle, plan: SharedTierPlan, settings: SharedStackSettings): SharedIsolationReport {
  const root = backend.stack;
  const keyParameter = new CfnParameter(root, "PapyrusSharedKmsKeyArn", {
    type: "AWS::SSM::Parameter::Value<String>",
    default: plan.keyArnParameter,
    description: `The ${plan.tier} shared stack's KMS key ARN, written by the ${plan.foundationStackName} stack.`,
  });
  const keyArn = keyParameter.valueAsString;
  const encryption = { sseEnabled: true, sseType: "KMS", kmsMasterKeyId: keyArn };

  // Amplify's model tables are made by a custom resource, so the key goes through the table wrapper.
  const amplifyTables = Object.values(backend.data.resources.cfnResources.amplifyDynamoDbTables);
  for (const table of amplifyTables) table.sseSpecification = encryption;

  const roles = findAllOfType(root, CfnRole);
  const boundary = boundaryPolicyArn(plan);
  const keyUsePolicy = { Version: "2012-10-17", Statement: [keyUseStatement(keyArn)] };
  for (const role of roles) {
    role.path = plan.rolePath;
    role.permissionsBoundary = boundary;
    appendInlinePolicy(role, `${plan.stackPrefix}-key-use`, keyUsePolicy);
  }
  // CDK writes the role of a custom resource provider as a raw resource, not a CfnRole.
  const rawRoles = findResourcesOfCfnType(root, "AWS::IAM::Role").filter((role) => !(role instanceof CfnRole));
  for (const role of rawRoles) {
    role.addPropertyOverride("Path", plan.rolePath);
    role.addPropertyOverride("PermissionsBoundary", boundary);
    appendInlinePolicyToRawRole(role, `${plan.stackPrefix}-key-use`, keyUsePolicy);
  }

  let tables = amplifyTables.length;
  for (const table of findAllOfType(root, CfnTable)) {
    table.sseSpecification = { sseEnabled: true, sseType: "KMS", kmsMasterKeyId: keyArn };
    tables += 1;
  }

  const buckets = findAllOfType(root, CfnBucket);
  for (const bucket of buckets) {
    // A bucket name that carries the stack's prefix lets the boundary and the dedicated deny match objects, which have no tags of their own.
    const named = bucket.bucketName;
    if (typeof named === "string" && !Token.isUnresolved(named)) {
      if (!named.startsWith(`${plan.stackPrefix}-`)) throw new Error(`Bucket ${bucket.node.path} is named ${named}, which does not start with ${plan.stackPrefix}-.`);
    } else {
      bucket.bucketName = Fn.join("-", [plan.stackPrefix, shortHash(bucket.node.path), Aws.ACCOUNT_ID, Aws.REGION]);
    }
    bucket.bucketEncryption = {
      serverSideEncryptionConfiguration: [{ bucketKeyEnabled: true, serverSideEncryptionByDefault: { sseAlgorithm: "aws:kms", kmsMasterKeyId: keyArn } }],
    };
  }

  const queues = findAllOfType(root, CfnQueue);
  for (const queue of queues) {
    // SQS-managed and KMS encryption exclude each other.
    queue.sqsManagedSseEnabled = undefined;
    queue.kmsMasterKeyId = keyArn;
  }

  let vectorResources = 0;
  for (const vectorBucket of findAllOfType(root, CfnVectorBucket)) {
    vectorBucket.encryptionConfiguration = { sseType: "aws:kms", kmsKeyArn: keyArn };
    vectorResources += 1;
  }
  for (const index of findAllOfType(root, CfnIndex)) {
    index.encryptionConfiguration = { sseType: "aws:kms", kmsKeyArn: keyArn };
    vectorResources += 1;
  }

  const functions = findResourcesOfCfnType(root, "AWS::Lambda::Function");
  const reservedFunctions: string[] = [];
  const functionTargets: Array<{ functionName: string; reserved?: number }> = [];
  let reservedTotal = 0;
  let logGroups = 0;
  for (const fn of functions) {
    const owner = functionOwnerId(fn);
    const name = `${plan.stackPrefix}-${slug(owner, 24)}-${shortHash(fn.node.path, 10)}`;
    fn.addPropertyOverride("FunctionName", name);
    const group = new CfnLogGroup(Stack.of(fn), `${owner}SharedLogGroup${shortHash(fn.node.path, 6)}`, {
      logGroupName: `/aws/lambda/${name}`,
      kmsKeyId: keyArn,
      retentionInDays: settings.logRetentionDays,
    });
    group.applyRemovalPolicy(RemovalPolicy.RETAIN);
    fn.addDependency(group);
    logGroups += 1;
    if (isInfrastructureFunction(fn)) {
      functionTargets.push({ functionName: name });
      continue;
    }
    const reserved = settings.reservedConcurrency.overrides[owner] ?? settings.reservedConcurrency.perFunction;
    fn.addPropertyOverride("ReservedConcurrentExecutions", reserved);
    reservedFunctions.push(owner);
    functionTargets.push({ functionName: name, reserved });
    reservedTotal += reserved;
  }
  if (reservedTotal > settings.reservedConcurrency.tierLimit) {
    throw new Error(
      `The ${plan.tier} shared stack reserves ${reservedTotal} concurrent executions across ${reservedFunctions.length} functions, over its tierLimit of ${settings.reservedConcurrency.tierLimit} in amplify/shared-stack/settings.ts.`,
    );
  }

  return {
    keyArnParameter: plan.keyArnParameter,
    roles: roles.length + rawRoles.length,
    functions: functions.length,
    reservedFunctions,
    functionTargets,
    reservedTotal,
    buckets: buckets.length,
    queues: queues.length,
    tables,
    logGroups,
    vectorResources,
  };
}
