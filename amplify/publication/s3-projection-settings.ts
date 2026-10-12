/**
 * Environment contract and IAM statements for the s3-projection publication.
 * Pure (no CDK imports) so both can be tested without synthesizing.
 */
export type S3ProjectionSettingsInput = {
  bucketName: string;
  bucketArn: string;
  keyValueStoreArn: string;
  deadLetterQueueUrl: string;
  deadLetterQueueArn: string;
  distributionArn?: string;
  distributionId?: string;
  publicHostName?: string;
  cache?: { htmlSMaxAgeSeconds?: number; invalidation?: "targeted" | "off" };
  projector?: string;
  staticDir?: string;
};

export type S3ProjectionPolicyStatementSpec = {
  actions: string[];
  resources: string[];
};

export const S3_PROJECTION_PROJECTOR_MODULE = "site_projector";
export const S3_PROJECTION_STATIC_DIRECTORY = "/var/task/site_static";

export function distributionIdFromArn(distributionArn: string): string {
  return distributionArn.slice(distributionArn.lastIndexOf("/") + 1);
}

export function s3ProjectionEnvironment(input: S3ProjectionSettingsInput): Record<string, string> {
  const environment: Record<string, string> = {
    PAPYRUS_PUBLICATION_KIND: "s3-projection",
    PAPYRUS_SITE_BUCKET: input.bucketName,
  };
  const distributionId = input.distributionId
    ?? (input.distributionArn !== undefined ? distributionIdFromArn(input.distributionArn) : undefined);
  if (distributionId !== undefined) environment.PAPYRUS_EDGE_DISTRIBUTION_ID = distributionId;
  environment.PAPYRUS_REDIRECTS_KVS_ARN = input.keyValueStoreArn;
  environment.PAPYRUS_PROJECTION_DLQ_URL = input.deadLetterQueueUrl;
  if (input.cache?.htmlSMaxAgeSeconds !== undefined) environment.PAPYRUS_HTML_S_MAXAGE_SECONDS = String(input.cache.htmlSMaxAgeSeconds);
  if (input.cache?.invalidation === "off") environment.PAPYRUS_EDGE_INVALIDATION = "off";
  if (input.publicHostName !== undefined) environment.PAPYRUS_SITE_PUBLIC_URL = `https://${input.publicHostName}`;
  if (input.projector !== undefined) environment.PAPYRUS_SITE_PROJECTOR = S3_PROJECTION_PROJECTOR_MODULE;
  if (input.staticDir !== undefined) environment.PAPYRUS_SITE_STATIC_DIR = S3_PROJECTION_STATIC_DIRECTORY;
  return environment;
}

export function s3ProjectionPolicyStatements(input: S3ProjectionSettingsInput): S3ProjectionPolicyStatementSpec[] {
  const statements: S3ProjectionPolicyStatementSpec[] = [
    { actions: ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"], resources: [`${input.bucketArn}/*`] },
    { actions: ["s3:ListBucket"], resources: [input.bucketArn] },
  ];
  if (input.distributionArn !== undefined && input.cache?.invalidation !== "off") {
    statements.push({ actions: ["cloudfront:CreateInvalidation"], resources: [input.distributionArn] });
  }
  statements.push(
    {
      actions: [
        "cloudfront-keyvaluestore:DescribeKeyValueStore",
        "cloudfront-keyvaluestore:GetKey",
        "cloudfront-keyvaluestore:PutKey",
        "cloudfront-keyvaluestore:DeleteKey",
        "cloudfront-keyvaluestore:UpdateKeys",
        "cloudfront-keyvaluestore:ListKeys",
      ],
      resources: [input.keyValueStoreArn],
    },
    { actions: ["sqs:SendMessage"], resources: [input.deadLetterQueueArn] },
  );
  return statements;
}

export type S3ProjectionBackendPlan = {
  enabled: boolean;
  siteFiles: Array<{ from: string; to: string }>;
  contentActionsMemorySize: number | undefined;
};

export const S3_PROJECTION_CONTENT_ACTIONS_MEMORY_MB = 2048;

export function planS3ProjectionBackend(
  publication: { projector?: string; staticDir?: string } | undefined,
): S3ProjectionBackendPlan {
  if (publication === undefined) return { enabled: false, siteFiles: [], contentActionsMemorySize: undefined };
  const siteFiles: Array<{ from: string; to: string }> = [];
  if (publication.projector !== undefined) {
    siteFiles.push({ from: publication.projector, to: `${S3_PROJECTION_PROJECTOR_MODULE}.py` });
  }
  if (publication.staticDir !== undefined) {
    siteFiles.push({ from: publication.staticDir, to: "site_static" });
  }
  return { enabled: true, siteFiles, contentActionsMemorySize: S3_PROJECTION_CONTENT_ACTIONS_MEMORY_MB };
}

export function contentActionsPublicationWiring<Statement>(
  publication: { environment: Record<string, string>; policyStatements: Statement[] } | undefined,
): { environment: Record<string, string>; policyStatements: Statement[] } {
  if (publication === undefined) return { environment: {}, policyStatements: [] };
  return { environment: publication.environment, policyStatements: publication.policyStatements };
}
