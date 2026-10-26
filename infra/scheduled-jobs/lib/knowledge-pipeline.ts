import { CfnParameter, Stack, StackProps, Tags } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";
import { KNOWLEDGE_STAGE_NAMES, DEFAULT_STAGE_TIMEOUT_SECONDS, type KnowledgeRunConfig } from "./knowledge-run-config";
import { PROJECTION_LOCK_PARAMETER_NAME, PROJECTION_LOCK_TABLE_NAME } from "./projection-lock-stack";
import { ScheduledContainerJob, type PipelineDefinition } from "./scheduled-container-job";

export const KNOWLEDGE_JOB_ID = "knowledge-run";

export const TREND_DRAFTS_STAGE = "trend-drafts";
/** The job script baked into the image (infra/knowledge-run/trend_drafts.py). It never exits non-zero. */
export const TREND_DRAFTS_COMMAND = ["python", "/opt/papyrus-jobs/trend_drafts.py"];

/** CloudFormation parameter values (tokens) that switch on and aim the optional trend-drafts step. */
export type TrendDraftsOptions = { enabled: string; endpoint: string; snapshotUrl: string };

export function knowledgeRunStackName(publication: string): string {
  return `papyrus-scheduled-job-${KNOWLEDGE_JOB_ID}-${publication}`;
}

/**
 * The knowledge pipeline as a configuration of the generic construct: the ten stages in order, each running
 * `papyrus knowledge cloud-run --stage <name>`, with the execution input read as
 * `{"publication": "<id>", "failStage": "<stage>"}` (both optional).
 */
export function knowledgePipeline(config: KnowledgeRunConfig, trendDrafts?: TrendDraftsOptions): PipelineDefinition {
  const input = "$states.context.Execution.Input";
  return {
    stages: [
      ...KNOWLEDGE_STAGE_NAMES.map((name) => ({
        name,
        command: ["papyrus", "knowledge", "cloud-run", "--stage", name],
        timeoutSeconds: config.stageTimeouts[name] ?? DEFAULT_STAGE_TIMEOUT_SECONDS,
      })),
      // Optional and last: after projection has published the snapshot. A failure here never fails the run.
      ...(trendDrafts ? [{
        name: TREND_DRAFTS_STAGE,
        command: TREND_DRAFTS_COMMAND,
        timeoutSeconds: 1800,
        retry: { maxAttempts: 0 },
        bestEffort: true,
        runIf: `'${trendDrafts.enabled}' = 'true'`,
        environment: { TREND_DRAFTS_ENDPOINT: trendDrafts.endpoint, TREND_DRAFTS_SNAPSHOT_URL: trendDrafts.snapshotUrl },
      }] : []),
    ],
    executionEnvironment: {
      KNOWLEDGE_PUBLICATION: `$exists(${input}.publication) ? ${input}.publication : '${config.publication}'`,
      KNOWLEDGE_EXECUTION_NAME: "$states.context.Execution.Name",
      KNOWLEDGE_EXECUTION_START: "$states.context.Execution.StartTime",
      KNOWLEDGE_FAIL_STAGE: `$exists(${input}.failStage) ? ${input}.failStage : ''`,
    },
  };
}

/** Container environment from config. Computed variables win over the free-form `environment` map. */
export function knowledgeEnvironment(config: KnowledgeRunConfig): Record<string, string> {
  return {
    ...config.environment,
    PAPYRUS_PROJECTION_LOCK_TABLE: PROJECTION_LOCK_TABLE_NAME,
    PAPYRUS_PROJECTION_LOCK_WAIT_SECONDS: String(config.lockWaitSeconds),
    KNOWLEDGE_PUBLICATION: config.publication,
    KNOWLEDGE_SITE_REPO: config.siteRepo,
    KNOWLEDGE_SITE_BRANCH: config.siteBranch,
    KNOWLEDGE_STATIC_SUBDIR: config.staticSubdir,
    KNOWLEDGE_OPENAI_KEY_PARAMETER: config.openAiKeyParameter,
    PAPYRUS_SITE_BUCKET: config.siteBucket,
    PAPYRUS_EDGE_DISTRIBUTION_ID: config.edgeDistributionId,
    PAPYRUS_REDIRECTS_KVS_ARN: config.redirectsKvsArn,
    PAPYRUS_PUBLICATION_KIND: "s3-projection",
    // The projection stages check this list against the deployed content-actions Lambda's before they write.
    PAPYRUS_PLUGINS: config.plugins.join(","),
    KNOWLEDGE_CONTENT_ACTIONS_FUNCTION: config.contentActionsFunction,
    KNOWLEDGE_AMPLIFY_APP_ID: config.amplifyAppId,
    AWS_REGION: config.region,
    HF_HOME: "/opt/hf",
    HF_HUB_OFFLINE: "1",
    // Honoured by the container only for an execution whose name starts with `test-`.
    KNOWLEDGE_ALLOW_TEST_FAILURE: "true",
    ...(config.beatsConfig ? { KNOWLEDGE_BEATS_CONFIG: config.beatsConfig } : {}),
    ...(config.conceptKinds ? { KNOWLEDGE_CONCEPT_KINDS: config.conceptKinds.join(",") } : {}),
    ...(config.monitorSources
      ? {
          KNOWLEDGE_MONITOR_SOURCES: config.monitorSources.join(","),
          KNOWLEDGE_MONITOR_WEEKS: String(config.monitorWeeks),
          ...(config.monitorSuggestions ? { KNOWLEDGE_MONITOR_SUGGESTIONS: String(config.monitorSuggestions) } : {}),
        }
      : {}),
  };
}

function ssmParameterArn(config: KnowledgeRunConfig, name: string): string {
  return `arn:aws:ssm:${config.region}:${config.account}:parameter${name}`;
}

/** Task role statements beyond the state bucket and ledger: everything is named in config, nothing is `*`. */
export function knowledgeTaskStatements(config: KnowledgeRunConfig): iam.PolicyStatement[] {
  const siteBucketArn = `arn:aws:s3:::${config.siteBucket}`;
  return [
    new iam.PolicyStatement({
      sid: "ProjectionLockTable",
      actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"],
      resources: [`arn:aws:dynamodb:${config.region}:${config.account}:table/${PROJECTION_LOCK_TABLE_NAME}`],
    }),
    new iam.PolicyStatement({
      sid: "ReadParameters",
      actions: ["ssm:GetParameter"],
      resources: [ssmParameterArn(config, PROJECTION_LOCK_PARAMETER_NAME), ssmParameterArn(config, config.openAiKeyParameter)],
    }),
    new iam.PolicyStatement({
      sid: "ReadContentActionsConfiguration",
      actions: ["lambda:GetFunctionConfiguration"],
      resources: [`arn:aws:lambda:${config.region}:${config.account}:function:${config.contentActionsFunction}`],
    }),
    new iam.PolicyStatement({
      sid: "ReadDeployedCommit",
      actions: ["amplify:ListJobs"],
      resources: ["", "/jobs/*"].map((suffix) => `arn:aws:amplify:${config.region}:${config.account}:apps/${config.amplifyAppId}/branches/${config.siteBranch}${suffix}`),
    }),
    new iam.PolicyStatement({
      sid: "SignAppSyncRequests",
      actions: ["appsync:GraphQL"],
      resources: ["Query", "Mutation"].map((type) => `arn:aws:appsync:${config.region}:${config.account}:apis/${config.appSyncApiId}/types/${type}/fields/*`),
    }),
    new iam.PolicyStatement({
      sid: "SiteBucketObjects",
      actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      resources: [`${siteBucketArn}/*`],
    }),
    new iam.PolicyStatement({ sid: "SiteBucketList", actions: ["s3:ListBucket", "s3:GetBucketLocation"], resources: [siteBucketArn] }),
    new iam.PolicyStatement({
      sid: "InvalidateEdge",
      actions: ["cloudfront:CreateInvalidation"],
      resources: [`arn:aws:cloudfront::${config.account}:distribution/${config.edgeDistributionId}`],
    }),
    new iam.PolicyStatement({
      sid: "RedirectsKeyValueStore",
      actions: [
        "cloudfront-keyvaluestore:DescribeKeyValueStore",
        "cloudfront-keyvaluestore:GetKey",
        "cloudfront-keyvaluestore:ListKeys",
        "cloudfront-keyvaluestore:PutKey",
        "cloudfront-keyvaluestore:DeleteKey",
        "cloudfront-keyvaluestore:UpdateKeys",
        "cloudfront:DescribeKeyValueStore",
      ],
      resources: [config.redirectsKvsArn],
    }),
  ];
}

export type KnowledgeRunStackProps = StackProps & { imageTag: string };

export class KnowledgeRunStack extends Stack {
  readonly job: ScheduledContainerJob;

  constructor(scope: Construct, id: string, config: KnowledgeRunConfig, props: KnowledgeRunStackProps) {
    const { imageTag, ...stackProps } = props;
    super(scope, id, {
      stackName: knowledgeRunStackName(config.publication),
      terminationProtection: true,
      ...stackProps,
    });
    Tags.of(this).add("Project", "Papyrus");
    Tags.of(this).add("Publication", config.publication);

    // Off by default. The three values are parameters so that enabling the step is a change set, not a code change.
    const trendDrafts = {
      enabled: new CfnParameter(this, "TrendDraftsEnabled", {
        type: "String", default: "false", allowedValues: ["true", "false"],
        description: "true: after a successful run, draft trend stories from the fresh snapshot (private Proposals, nothing published).",
      }).valueAsString,
      endpoint: new CfnParameter(this, "TrendDraftsEndpoint", {
        type: "String", default: "", allowedPattern: "^(https://[a-z0-9]+\\.appsync-api\\.[a-z0-9-]+\\.amazonaws\\.com/graphql)?$",
        description: "The publication's AppSync GraphQL endpoint (the step signs its requests with the task role).",
      }).valueAsString,
      snapshotUrl: new CfnParameter(this, "TrendDraftsSnapshotUrl", {
        type: "String", default: "", allowedPattern: "^(https://[^ ]+/_data/knowledge/index\\.json)?$",
        description: "The published snapshot index, such as https://shipped.anth.us/_data/knowledge/index.json.",
      }).valueAsString,
    };
    this.job = new ScheduledContainerJob(this, "Job", {
      jobId: KNOWLEDGE_JOB_ID,
      publication: config.publication,
      pipeline: knowledgePipeline(config, trendDrafts),
      imageTag,
      defaultSize: { vCpu: config.vCpu, memoryMiB: config.memoryMiB, ephemeralStorageGiB: config.ephemeralStorageGiB },
      defaultStageTimeoutSeconds: DEFAULT_STAGE_TIMEOUT_SECONDS,
      schedule: { expression: config.schedule, state: config.scheduleState },
      scheduleInput: { publication: config.publication },
      environment: knowledgeEnvironment(config),
      stateBucketEnvVar: "KNOWLEDGE_STATE_BUCKET",
      ledgerTableEnvVar: "KNOWLEDGE_LEDGER_TABLE",
      taskPolicyStatements: knowledgeTaskStatements(config),
      alarmEmailParameter: config.alarmEmailParameter,
    });
    this.job.addOutputs(this);
  }
}
