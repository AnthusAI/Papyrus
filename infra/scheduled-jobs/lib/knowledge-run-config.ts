import type { AmplifyAppShellSiteConfig } from "../../amplify-app-shell/lib/site-config";

/** The pipeline stages, in execution order. `projection` must stay last: it publishes to the live site. */
export const KNOWLEDGE_STAGE_NAMES = [
  "corpus-sync",
  "topic-model",
  "typed-extraction",
  "publish-run",
  "ai-review",
  "publish-relations",
  "snapshot",
  "archive",
  "wiki-sync",
  "projection",
] as const;

export const DEFAULT_SCHEDULE = "cron(0 5 ? * MON *)";
export const DEFAULT_VCPU = 4;
export const DEFAULT_MEMORY_MIB = 16384;
export const DEFAULT_EPHEMERAL_STORAGE_GIB = 40;
export const DEFAULT_STAGE_TIMEOUT_SECONDS = 7200;
export const DEFAULT_LOCK_WAIT_SECONDS = 1800;
export const DEFAULT_MONITOR_WEEKS = 52;
export const DEFAULT_TREND_SNAPSHOT_MAX_AGE_DAYS = 1;
/** The trend window is whole weeks, one to four: the snapshot counts weekly and keeps eight weeks. */
export const TREND_WINDOW_DAYS = [7, 14, 21, 28] as const;
/** The sources `papyrus knowledge corpus export --monitor-sources` understands. */
export const MONITOR_SOURCES = ["huggingface", "routed"] as const;

const VALID_VCPU = [1, 2, 4, 8, 16];

/** The `knowledgeRun` block of a publication's infra/site.json, as written. */
export type KnowledgeRunSettings = {
  schedule?: string;
  scheduleState?: "ENABLED" | "DISABLED";
  vCpu?: number;
  memoryMiB?: number;
  ephemeralStorageGiB?: number;
  siteBucket: string;
  edgeDistributionId: string;
  redirectsKvsArn: string;
  appSyncApiId: string;
  /** Name of the site's deployed content-actions Lambda: the projection stage checks its plugin list against `plugins`. */
  /** The CMS Amplify app: the stages check out the commit of its latest successful deploy of `siteBranch`. */
  amplifyAppId: string;
  contentActionsFunction: string;
  /** The site's enabled plugins (what `PAPYRUS_PLUGINS` holds on that Lambda); without them a projection omits plugin pages. */
  plugins?: string[];
  siteRepo?: string;
  siteBranch?: string;
  staticSubdir?: string;
  beatsConfig?: string;
  conceptKinds?: string[];
  /** Monitor sources whose delivered References count in the Knowledge Map as data, never as pages (docs/knowledge-cloud-run.md). */
  monitorSources?: string[];
  /** How many weeks back a monitor record counts (its source date decides); default 52. */
  monitorWeeks?: number;
  /** How many monitor records the AI review stage suggests promoting in one soft review request each week; default 0 (none). */
  monitorSuggestions?: number;
  /** The Cited Trends window in days (7, 14, 21 or 28): the last N days against the N before. Unset means the command's own 28. */
  trendWindowDays?: number;
  /** How many days older than the execution's start the published snapshot's asOf may be for the trend-drafts step to use it; default 1. */
  trendSnapshotMaxAgeDays?: number;
  /** Days an entity that anchored a story draft rests before it can anchor another (0 turns it off). Unset means the command's own 7. */
  trendCooldownDays?: number;
  openAiKeyParameter?: string;
  alarmEmailParameter?: string;
  lockWaitSeconds?: number;
  stageTimeouts?: Record<string, number>;
  environment?: Record<string, string>;
};

/** `KnowledgeRunSettings` with every default applied, for one publication in one account. */
export type KnowledgeRunConfig = {
  publication: string;
  account: string;
  region: string;
  schedule: string;
  scheduleState: "ENABLED" | "DISABLED";
  vCpu: number;
  memoryMiB: number;
  ephemeralStorageGiB: number;
  siteBucket: string;
  edgeDistributionId: string;
  redirectsKvsArn: string;
  appSyncApiId: string;
  amplifyAppId: string;
  contentActionsFunction: string;
  plugins: string[];
  siteRepo: string;
  siteBranch: string;
  staticSubdir: string;
  beatsConfig?: string;
  conceptKinds?: string[];
  monitorSources?: string[];
  monitorWeeks: number;
  monitorSuggestions: number;
  trendWindowDays?: number;
  trendSnapshotMaxAgeDays: number;
  trendCooldownDays?: number;
  openAiKeyParameter: string;
  alarmEmailParameter: string;
  lockWaitSeconds: number;
  stageTimeouts: Record<string, number>;
  environment: Record<string, string>;
};

const SITE_BUCKET_PATTERN = /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/;
const DISTRIBUTION_ID_PATTERN = /^E[A-Z0-9]{8,}$/;
const KVS_ARN_PATTERN = /^arn:aws:cloudfront::\d{12}:key-value-store\/[0-9a-f-]{36}$/;
const AMPLIFY_APP_ID_PATTERN = /^d[a-z0-9]{8,20}$/;
const LAMBDA_NAME_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const PLUGIN_PATTERN = /^[a-z][a-z0-9-]*$/;
const APPSYNC_API_ID_PATTERN = /^[a-z0-9]{20,32}$/;
const GIT_URL_PATTERN = /^https:\/\/[A-Za-z0-9.-]+\/[A-Za-z0-9_.\/-]+$/;
const BRANCH_PATTERN = /^[A-Za-z0-9][A-Za-z0-9/_.-]*$/;
const REPO_PATH_PATTERN = /^[A-Za-z0-9_.-]+(\/[A-Za-z0-9_.-]+)*$/;
const SSM_NAME_PATTERN = /^\/[A-Za-z0-9_.\-\/]+$/;
const ENV_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
const CRON_PATTERN = /^(cron\(.+\)|rate\(.+\))$/;
const KIND_PATTERN = /^[a-z][a-z0-9_]*$/;

function fail(field: string, problem: string): never {
  throw new Error(`site.json: knowledgeRun${field ? `.${field}` : ""} ${problem}`);
}

function requireString(value: unknown, field: string, pattern?: RegExp, hint?: string): string {
  if (typeof value !== "string" || value.trim() === "") fail(field, "must be a non-empty string");
  if (pattern && !pattern.test(value as string)) fail(field, `is invalid${hint ? ` (${hint})` : ""}: ${JSON.stringify(value)}`);
  return value as string;
}

function optionalString(value: unknown, field: string, pattern?: RegExp, hint?: string): string | undefined {
  return value === undefined ? undefined : requireString(value, field, pattern, hint);
}

function optionalInteger(value: unknown, field: string, min: number, max: number): number | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) {
    fail(field, `must be an integer from ${min} to ${max}, got ${JSON.stringify(value)}`);
  }
  return value as number;
}

function optionalTrendWindowDays(value: unknown): number | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "number" || !(TREND_WINDOW_DAYS as readonly number[]).includes(value)) {
    fail("trendWindowDays", `must be one of ${TREND_WINDOW_DAYS.join(", ")} (the snapshot counts whole weeks), got ${JSON.stringify(value)}`);
  }
  return value as number;
}

function optionalPlugins(value: unknown): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string" || !PLUGIN_PATTERN.test(entry))) {
    fail("plugins", "must be an array of plugin names such as \"newsletter\"");
  }
  return [...new Set(value as string[])].sort();
}

function rejectUnknownKeys(record: Record<string, unknown>, allowed: string[]): void {
  for (const key of Object.keys(record)) {
    if (!allowed.includes(key)) fail(key, `is not a known field (known: ${allowed.join(", ")})`);
  }
}

export function parseKnowledgeRun(raw: unknown): KnowledgeRunSettings {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) fail("", "must be an object");
  const record = raw as Record<string, unknown>;
  rejectUnknownKeys(record, [
    "schedule", "scheduleState", "vCpu", "memoryMiB", "ephemeralStorageGiB", "siteBucket", "edgeDistributionId",
    "redirectsKvsArn", "appSyncApiId", "amplifyAppId", "contentActionsFunction", "plugins", "siteRepo", "siteBranch", "staticSubdir", "beatsConfig", "conceptKinds",
    "monitorSources", "monitorWeeks", "monitorSuggestions", "trendWindowDays", "trendSnapshotMaxAgeDays", "trendCooldownDays", "openAiKeyParameter", "alarmEmailParameter", "lockWaitSeconds", "stageTimeouts", "environment",
  ]);

  const scheduleState = record.scheduleState;
  if (scheduleState !== undefined && scheduleState !== "ENABLED" && scheduleState !== "DISABLED") {
    fail("scheduleState", `must be "ENABLED" or "DISABLED", got ${JSON.stringify(scheduleState)}`);
  }
  const vCpu = optionalInteger(record.vCpu, "vCpu", 1, 16);
  if (vCpu !== undefined && !VALID_VCPU.includes(vCpu)) fail("vCpu", `must be one of ${VALID_VCPU.join(", ")} (Fargate), got ${vCpu}`);

  let conceptKinds: string[] | undefined;
  if (record.conceptKinds !== undefined) {
    if (!Array.isArray(record.conceptKinds) || record.conceptKinds.length === 0) fail("conceptKinds", "must be a non-empty array of strings");
    conceptKinds = (record.conceptKinds as unknown[]).map((kind, index) => requireString(kind, `conceptKinds[${index}]`, KIND_PATTERN, "lowercase snake_case"));
  }

  let monitorSources: string[] | undefined;
  if (record.monitorSources !== undefined) {
    if (!Array.isArray(record.monitorSources) || record.monitorSources.length === 0) fail("monitorSources", "must be a non-empty array of strings");
    monitorSources = [...new Set((record.monitorSources as unknown[]).map((source, index) => requireString(source, `monitorSources[${index}]`)))];
    for (const source of monitorSources) {
      if (!(MONITOR_SOURCES as readonly string[]).includes(source)) fail("monitorSources", `names an unsupported source ${JSON.stringify(source)} (supported: ${MONITOR_SOURCES.join(", ")})`);
    }
  }

  let stageTimeouts: Record<string, number> | undefined;
  if (record.stageTimeouts !== undefined) {
    const timeouts = record.stageTimeouts as Record<string, unknown>;
    if (typeof timeouts !== "object" || timeouts === null || Array.isArray(timeouts)) fail("stageTimeouts", "must be an object of stage name to seconds");
    stageTimeouts = {};
    for (const [stage, seconds] of Object.entries(timeouts)) {
      if (!(KNOWLEDGE_STAGE_NAMES as readonly string[]).includes(stage)) {
        fail(`stageTimeouts.${stage}`, `is not a stage (stages: ${KNOWLEDGE_STAGE_NAMES.join(", ")})`);
      }
      stageTimeouts[stage] = optionalInteger(seconds, `stageTimeouts.${stage}`, 60, 86400) as number;
    }
  }

  let environment: Record<string, string> | undefined;
  if (record.environment !== undefined) {
    const entries = record.environment as Record<string, unknown>;
    if (typeof entries !== "object" || entries === null || Array.isArray(entries)) fail("environment", "must be an object of strings");
    environment = {};
    for (const [name, value] of Object.entries(entries)) {
      if (!ENV_NAME_PATTERN.test(name)) fail(`environment.${name}`, "is not a valid environment variable name");
      if (typeof value !== "string") fail(`environment.${name}`, "must be a string");
      environment[name] = value as string;
    }
  }

  return {
    schedule: optionalString(record.schedule, "schedule", CRON_PATTERN, "EventBridge Scheduler cron(...) or rate(...) expression"),
    scheduleState: scheduleState as "ENABLED" | "DISABLED" | undefined,
    vCpu,
    memoryMiB: optionalInteger(record.memoryMiB, "memoryMiB", 2048, 122880),
    ephemeralStorageGiB: optionalInteger(record.ephemeralStorageGiB, "ephemeralStorageGiB", 21, 200),
    siteBucket: requireString(record.siteBucket, "siteBucket", SITE_BUCKET_PATTERN, "S3 bucket name"),
    edgeDistributionId: requireString(record.edgeDistributionId, "edgeDistributionId", DISTRIBUTION_ID_PATTERN, "CloudFront distribution id"),
    redirectsKvsArn: requireString(record.redirectsKvsArn, "redirectsKvsArn", KVS_ARN_PATTERN, "CloudFront KeyValueStore ARN"),
    appSyncApiId: requireString(record.appSyncApiId, "appSyncApiId", APPSYNC_API_ID_PATTERN, "AppSync API id"),
    amplifyAppId: requireString(record.amplifyAppId, "amplifyAppId", AMPLIFY_APP_ID_PATTERN, "Amplify app id"),
    contentActionsFunction: requireString(record.contentActionsFunction, "contentActionsFunction", LAMBDA_NAME_PATTERN, "Lambda function name"),
    plugins: optionalPlugins(record.plugins),
    siteRepo: optionalString(record.siteRepo, "siteRepo", GIT_URL_PATTERN, "https git URL"),
    siteBranch: optionalString(record.siteBranch, "siteBranch", BRANCH_PATTERN),
    staticSubdir: optionalString(record.staticSubdir, "staticSubdir", REPO_PATH_PATTERN, "relative path inside the site repository"),
    beatsConfig: optionalString(record.beatsConfig, "beatsConfig", REPO_PATH_PATTERN, "relative path inside the site repository"),
    conceptKinds,
    monitorSources,
    monitorWeeks: optionalInteger(record.monitorWeeks, "monitorWeeks", 1, 260),
    monitorSuggestions: optionalInteger(record.monitorSuggestions, "monitorSuggestions", 0, 20),
    trendWindowDays: optionalTrendWindowDays(record.trendWindowDays),
    trendSnapshotMaxAgeDays: optionalInteger(record.trendSnapshotMaxAgeDays, "trendSnapshotMaxAgeDays", 0, 7),
    trendCooldownDays: optionalInteger(record.trendCooldownDays, "trendCooldownDays", 0, 365),
    openAiKeyParameter: optionalString(record.openAiKeyParameter, "openAiKeyParameter", SSM_NAME_PATTERN, "SSM parameter name starting with /"),
    alarmEmailParameter: optionalString(record.alarmEmailParameter, "alarmEmailParameter", SSM_NAME_PATTERN, "SSM parameter name starting with /"),
    lockWaitSeconds: optionalInteger(record.lockWaitSeconds, "lockWaitSeconds", 0, 86400),
    stageTimeouts,
    environment,
  };
}

/** Applies the defaults. The site must say where it deploys (`aws.accountId`, `aws.region`) and carry a `knowledgeRun` block. */
export function resolveKnowledgeRunConfig(site: Pick<AmplifyAppShellSiteConfig, "siteId" | "repository" | "aws" | "knowledgeRun">): KnowledgeRunConfig {
  if (site.knowledgeRun === undefined) throw new Error(`site.json: site "${site.siteId}" has no knowledgeRun block`);
  const account = site.aws?.accountId;
  const region = site.aws?.region;
  if (!account || !region) throw new Error(`site.json: site "${site.siteId}" needs aws.accountId and aws.region to deploy the knowledge run`);
  const settings = parseKnowledgeRun(site.knowledgeRun);
  const publication = site.siteId;
  const memoryMiB = settings.memoryMiB ?? DEFAULT_MEMORY_MIB;
  const vCpu = settings.vCpu ?? DEFAULT_VCPU;
  if (memoryMiB < vCpu * 2048) fail("memoryMiB", `must be at least 2048 MiB per vCPU (${vCpu * 2048}) for ${vCpu} vCPU`);
  return {
    publication,
    account,
    region,
    schedule: settings.schedule ?? DEFAULT_SCHEDULE,
    scheduleState: settings.scheduleState ?? "ENABLED",
    vCpu,
    memoryMiB,
    ephemeralStorageGiB: settings.ephemeralStorageGiB ?? DEFAULT_EPHEMERAL_STORAGE_GIB,
    siteBucket: settings.siteBucket,
    edgeDistributionId: settings.edgeDistributionId,
    redirectsKvsArn: settings.redirectsKvsArn,
    appSyncApiId: settings.appSyncApiId,
    amplifyAppId: settings.amplifyAppId,
    contentActionsFunction: settings.contentActionsFunction,
    plugins: settings.plugins ?? [],
    siteRepo: settings.siteRepo ?? site.repository,
    siteBranch: settings.siteBranch ?? "main",
    staticSubdir: settings.staticSubdir ?? "web",
    beatsConfig: settings.beatsConfig,
    conceptKinds: settings.conceptKinds,
    monitorSources: settings.monitorSources,
    monitorWeeks: settings.monitorWeeks ?? DEFAULT_MONITOR_WEEKS,
    monitorSuggestions: settings.monitorSuggestions ?? 0,
    trendWindowDays: settings.trendWindowDays,
    trendSnapshotMaxAgeDays: settings.trendSnapshotMaxAgeDays ?? DEFAULT_TREND_SNAPSHOT_MAX_AGE_DAYS,
    trendCooldownDays: settings.trendCooldownDays,
    openAiKeyParameter: settings.openAiKeyParameter ?? `/papyrus/${publication}/openai-api-key`,
    alarmEmailParameter: settings.alarmEmailParameter ?? `/papyrus/${publication}/knowledge-run/alarm-email`,
    lockWaitSeconds: settings.lockWaitSeconds ?? DEFAULT_LOCK_WAIT_SECONDS,
    stageTimeouts: settings.stageTimeouts ?? {},
    environment: settings.environment ?? {},
  };
}
