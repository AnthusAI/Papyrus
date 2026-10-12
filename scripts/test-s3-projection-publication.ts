import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { App, Stack } from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Match, Template } from "aws-cdk-lib/assertions";
import { addProjectionRetries, addS3ProjectionPublication, type S3ProjectionPublicationProps } from "../amplify/publication/s3-projection";
import {
  contentActionsPublicationWiring,
  planS3ProjectionBackend,
  s3ProjectionEnvironment,
  s3ProjectionPolicyStatements,
} from "../amplify/publication/s3-projection-settings";
import { validatePublicationConfig } from "../amplify/site-backend-config";
import { copySiteFiles, siteFilesContentHash } from "../amplify/functions/shared/python-bundle";

const edgeArn = "arn:aws:cloudfront::123456789012:distribution/E3UMOOJRMY7FK7";
const certificateArn = "arn:aws:acm:us-east-1:123456789012:certificate/abc-123";

function problemsOf(publication: unknown): string {
  return validatePublicationConfig(publication).join("|");
}

assert.deepEqual(validatePublicationConfig({ kind: "s3-projection" }), []);
assert.deepEqual(
  validatePublicationConfig({
    kind: "s3-projection",
    projector: "web/projector.py",
    staticDir: "web/static",
    edgeDistributionArn: edgeArn,
  }),
  [],
);
assert.match(problemsOf({ kind: "amplify-reader" }), /kind must be "s3-projection"/);
assert.match(problemsOf({ kind: "s3-projection", edgeDistributionArn: "arn:aws:s3:::bucket" }), /CloudFront distribution ARN/);
assert.match(problemsOf({ kind: "s3-projection", edgeDistributionArn: edgeArn, distribution: { create: true } }), /mutually exclusive/);
assert.deepEqual(validatePublicationConfig({ kind: "s3-projection", edgeDistributionArn: edgeArn, distribution: { create: false } }), []);
assert.match(problemsOf({ kind: "s3-projection", distribution: { create: true, aliases: ["a.example.org"] } }), /certificateArn or acm/);
assert.deepEqual(
  validatePublicationConfig({ kind: "s3-projection", distribution: { create: true, aliases: ["a.example.org"], certificateArn } }),
  [],
);
for (const projector of ["../x.py", "/abs/x.py", "web/projector.js", "web/../../x.py", ""]) {
  assert.match(problemsOf({ kind: "s3-projection", projector }), /projector/, projector);
}
for (const staticDir of ["../static", "/abs/static", "a/../../static"]) {
  assert.match(problemsOf({ kind: "s3-projection", staticDir }), /staticDir/, staticDir);
}

const settingsInput = {
  bucketName: "site-bucket",
  bucketArn: "arn:aws:s3:::site-bucket",
  keyValueStoreArn: "arn:aws:cloudfront::123456789012:key-value-store/kvs-1",
  deadLetterQueueUrl: "https://sqs.us-east-1.amazonaws.com/123456789012/dlq",
  deadLetterQueueArn: "arn:aws:sqs:us-east-1:123456789012:dlq",
};
assert.deepEqual(s3ProjectionEnvironment(settingsInput), {
  PAPYRUS_PUBLICATION_KIND: "s3-projection",
  PAPYRUS_SITE_BUCKET: "site-bucket",
  PAPYRUS_REDIRECTS_KVS_ARN: settingsInput.keyValueStoreArn,
  PAPYRUS_PROJECTION_DLQ_URL: settingsInput.deadLetterQueueUrl,
});
assert.deepEqual(
  s3ProjectionEnvironment({
    ...settingsInput,
    distributionArn: edgeArn,
    projector: "web/projector.py",
    staticDir: "web/static",
  }),
  {
    PAPYRUS_PUBLICATION_KIND: "s3-projection",
    PAPYRUS_SITE_BUCKET: "site-bucket",
    PAPYRUS_EDGE_DISTRIBUTION_ID: "E3UMOOJRMY7FK7",
    PAPYRUS_REDIRECTS_KVS_ARN: settingsInput.keyValueStoreArn,
    PAPYRUS_PROJECTION_DLQ_URL: settingsInput.deadLetterQueueUrl,
    PAPYRUS_SITE_PROJECTOR: "site_projector",
    PAPYRUS_SITE_STATIC_DIR: "/var/task/site_static",
  },
);
assert.equal(
  s3ProjectionEnvironment({ ...settingsInput, distributionId: "EABC", distributionArn: edgeArn, publicHostName: "news.example.org" })
    .PAPYRUS_SITE_PUBLIC_URL,
  "https://news.example.org",
);

const statementsWithoutDistribution = s3ProjectionPolicyStatements(settingsInput);
assert.equal(statementsWithoutDistribution.some((statement) => statement.actions.includes("cloudfront:CreateInvalidation")), false);
const statementsWithDistribution = s3ProjectionPolicyStatements({ ...settingsInput, distributionArn: edgeArn });
assert.deepEqual(statementsWithDistribution, [
  { actions: ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"], resources: ["arn:aws:s3:::site-bucket/*"] },
  { actions: ["s3:ListBucket"], resources: ["arn:aws:s3:::site-bucket"] },
  { actions: ["cloudfront:CreateInvalidation"], resources: [edgeArn] },
  {
    actions: [
      "cloudfront-keyvaluestore:DescribeKeyValueStore",
      "cloudfront-keyvaluestore:GetKey",
      "cloudfront-keyvaluestore:PutKey",
      "cloudfront-keyvaluestore:DeleteKey",
      "cloudfront-keyvaluestore:UpdateKeys",
      "cloudfront-keyvaluestore:ListKeys",
    ],
    resources: [settingsInput.keyValueStoreArn],
  },
  { actions: ["sqs:SendMessage"], resources: [settingsInput.deadLetterQueueArn] },
]);

assert.deepEqual(planS3ProjectionBackend(undefined), { enabled: false, siteFiles: [], contentActionsMemorySize: undefined });
assert.deepEqual(contentActionsPublicationWiring(undefined), { environment: {}, policyStatements: [] });
assert.deepEqual(planS3ProjectionBackend({ projector: "web/projector.py", staticDir: "web/static" }), {
  enabled: true,
  siteFiles: [
    { from: "web/projector.py", to: "site_projector.py" },
    { from: "web/static", to: "site_static" },
  ],
  contentActionsMemorySize: 2048,
});
assert.deepEqual(planS3ProjectionBackend({}).siteFiles, []);

const siteRoot = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-site-files-"));
const originalCwd = process.cwd();
try {
  fs.mkdirSync(path.join(siteRoot, "web/static/css"), { recursive: true });
  fs.mkdirSync(path.join(siteRoot, "web/static/__pycache__"), { recursive: true });
  fs.writeFileSync(path.join(siteRoot, "web/projector.py"), "PROJECTOR = 1\n");
  fs.writeFileSync(path.join(siteRoot, "web/static/css/site.css"), "body{}\n");
  fs.writeFileSync(path.join(siteRoot, "web/static/__pycache__/x.pyc"), "bytecode");
  process.chdir(siteRoot);
  const siteFiles = planS3ProjectionBackend({ projector: "web/projector.py", staticDir: "web/static" }).siteFiles;
  const bundleDir = path.join(siteRoot, "bundle");
  fs.mkdirSync(bundleDir);
  copySiteFiles(bundleDir, siteFiles);
  assert.equal(fs.readFileSync(path.join(bundleDir, "site_projector.py"), "utf8"), "PROJECTOR = 1\n");
  assert.equal(fs.readFileSync(path.join(bundleDir, "site_static/css/site.css"), "utf8"), "body{}\n");
  assert.equal(fs.existsSync(path.join(bundleDir, "site_static/__pycache__")), false);
  const hashBefore = siteFilesContentHash(siteFiles);
  fs.writeFileSync(path.join(siteRoot, "web/projector.py"), "PROJECTOR = 2\n");
  assert.notEqual(siteFilesContentHash(siteFiles), hashBefore);
  assert.throws(() => copySiteFiles(bundleDir, [{ from: "missing.py", to: "x.py" }]), /does not exist/);
} finally {
  process.chdir(originalCwd);
  fs.rmSync(siteRoot, { recursive: true, force: true });
}

function synthesize(props: S3ProjectionPublicationProps) {
  const app = new App();
  const stack = new Stack(app, "ProjectionHarness", { env: { account: "123456789012", region: "us-east-1" } });
  const publication = addS3ProjectionPublication(stack, props);
  return { template: Template.fromStack(stack), publication };
}

function assertSiteBucketIsPrivateAndVersioned(template: Template) {
  template.resourceCountIs("AWS::S3::Bucket", 1);
  template.hasResourceProperties("AWS::S3::Bucket", {
    VersioningConfiguration: { Status: "Enabled" },
    PublicAccessBlockConfiguration: {
      BlockPublicAcls: true,
      BlockPublicPolicy: true,
      IgnorePublicAcls: true,
      RestrictPublicBuckets: true,
    },
    BucketEncryption: {
      ServerSideEncryptionConfiguration: [{ ServerSideEncryptionByDefault: { SSEAlgorithm: "AES256" } }],
    },
    LifecycleConfiguration: {
      Rules: [Match.objectLike({ NoncurrentVersionExpiration: { NoncurrentDays: 90 }, Status: "Enabled" })],
    },
  });
  template.hasResource("AWS::S3::Bucket", { DeletionPolicy: "Retain", UpdateReplacePolicy: "Retain" });
  template.hasResourceProperties("AWS::S3::BucketPolicy", {
    PolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({
          Effect: "Deny",
          Action: "s3:*",
          Condition: { Bool: { "aws:SecureTransport": "false" } },
        }),
      ]),
    },
  });
  const policies = Object.values(template.findResources("AWS::S3::BucketPolicy"));
  for (const policy of policies) {
    for (const statement of policy.Properties.PolicyDocument.Statement) {
      if (statement.Effect === "Allow") {
        assert.deepEqual(statement.Principal, { Service: "cloudfront.amazonaws.com" });
        assert.deepEqual(statement.Action, "s3:GetObject");
        assert.ok(statement.Condition?.StringEquals?.["AWS:SourceArn"] ?? statement.Condition?.StringEquals?.["aws:SourceArn"]);
      }
    }
  }
}

function assertSharedParts(template: Template) {
  assertSiteBucketIsPrivateAndVersioned(template);
  template.resourceCountIs("AWS::CloudFront::KeyValueStore", 1);
  template.hasResourceProperties("AWS::CloudFront::Function", {
    FunctionConfig: { Runtime: "cloudfront-js-2.0", KeyValueStoreAssociations: [Match.objectLike({ KeyValueStoreARN: Match.anyValue() })] },
    AutoPublish: true,
    FunctionCode: Match.stringLikeRegexp("cf\\.kvs\\(\\)"),
  });
  template.hasResourceProperties("AWS::SQS::Queue", { SqsManagedSseEnabled: true, MessageRetentionPeriod: 14 * 24 * 60 * 60 });
}

function oacStatements(template: Template) {
  return Object.values(template.findResources("AWS::S3::BucketPolicy")).flatMap((policy) =>
    policy.Properties.PolicyDocument.Statement.filter((statement: { Effect: string }) => statement.Effect === "Allow"),
  );
}

{
  const { template, publication } = synthesize({ kind: "s3-projection", edgeDistributionArn: edgeArn, projector: "web/projector.py" });
  assertSharedParts(template);
  template.resourceCountIs("AWS::CloudFront::Distribution", 0);
  const allowed = oacStatements(template);
  assert.equal(allowed.length, 1);
  assert.deepEqual(allowed[0].Condition, { StringEquals: { "aws:SourceArn": edgeArn } });
  assert.equal(publication.distribution, undefined);
  assert.equal(publication.environment.PAPYRUS_EDGE_DISTRIBUTION_ID, "E3UMOOJRMY7FK7");
  assert.equal(publication.environment.PAPYRUS_SITE_PUBLIC_URL, undefined);
  assert.equal(publication.environment.PAPYRUS_SITE_PROJECTOR, "site_projector");
  assert.equal(publication.environment.PAPYRUS_SITE_STATIC_DIR, undefined);
  const stack = Stack.of(publication.bucket);
  const rendered = JSON.stringify(publication.policyStatements.map((statement) => stack.resolve(statement.toStatementJson())));
  assert.ok(rendered.includes("cloudfront:CreateInvalidation"));
  assert.ok(rendered.includes(edgeArn));
  assert.ok(rendered.includes("cloudfront-keyvaluestore:UpdateKeys"));
  assert.ok(rendered.includes("sqs:SendMessage"));
  assert.equal(publication.policyStatements.length, 5);
}

{
  const { template, publication } = synthesize({ kind: "s3-projection", distribution: { create: true }, staticDir: "web/static" });
  assertSharedParts(template);
  template.resourceCountIs("AWS::CloudFront::OriginAccessControl", 1);
  template.resourceCountIs("AWS::CloudFront::Distribution", 1);
  template.hasResourceProperties("AWS::CloudFront::Distribution", {
    DistributionConfig: Match.objectLike({
      DefaultRootObject: "index.html",
      HttpVersion: "http2and3",
      Enabled: true,
      DefaultCacheBehavior: Match.objectLike({
        ViewerProtocolPolicy: "redirect-to-https",
        Compress: true,
        FunctionAssociations: [Match.objectLike({ EventType: "viewer-request" })],
      }),
      CustomErrorResponses: Match.arrayWith([
        Match.objectLike({ ErrorCode: 404, ResponseCode: 404, ResponsePagePath: "/404.html" }),
      ]),
      Origins: [Match.objectLike({ OriginAccessControlId: Match.anyValue(), S3OriginConfig: { OriginAccessIdentity: "" } })],
    }),
  });
  const distributionConfig = Object.values(template.findResources("AWS::CloudFront::Distribution"))[0].Properties.DistributionConfig;
  assert.equal(distributionConfig.Logging, undefined);
  assert.equal(distributionConfig.Aliases, undefined);
  const allowed = oacStatements(template);
  assert.equal(allowed.length, 1);
  assert.ok(allowed[0].Condition.StringEquals["AWS:SourceArn"]["Fn::Join"] || allowed[0].Condition.StringEquals["AWS:SourceArn"]["Fn::Sub"]);
  assert.ok(JSON.stringify(allowed[0].Condition).includes("SiteDistribution"));
  assert.ok(publication.distribution !== undefined);
  assert.ok(publication.environment.PAPYRUS_EDGE_DISTRIBUTION_ID !== undefined);
  assert.ok(publication.environment.PAPYRUS_SITE_PUBLIC_URL.startsWith("https://"));
  assert.equal(publication.environment.PAPYRUS_SITE_STATIC_DIR, "/var/task/site_static");
  assert.equal(publication.environment.PAPYRUS_SITE_PROJECTOR, undefined);
  const stack = Stack.of(publication.bucket);
  const invalidation = publication.policyStatements
    .map((statement) => stack.resolve(statement.toStatementJson()))
    .find((statement) => JSON.stringify(statement).includes("CreateInvalidation"));
  assert.ok(JSON.stringify(invalidation).includes("SiteDistribution"));
}

{
  const { template, publication } = synthesize({
    kind: "s3-projection",
    distribution: { create: true, aliases: ["news.example.org", "www.example.org"], certificateArn },
  });
  assertSharedParts(template);
  template.hasResourceProperties("AWS::CloudFront::Distribution", {
    DistributionConfig: Match.objectLike({
      Aliases: ["news.example.org", "www.example.org"],
      ViewerCertificate: Match.objectLike({ AcmCertificateArn: certificateArn }),
    }),
  });
  assert.equal(publication.environment.PAPYRUS_SITE_PUBLIC_URL, "https://news.example.org");
}

{
  const { template, publication } = synthesize({
    kind: "s3-projection",
    distribution: {
      create: true,
      aliases: ["news.example.org"],
      acm: { hostedZoneId: "Z123456789", hostedZoneName: "example.org" },
    },
  });
  assertSharedParts(template);
  template.resourceCountIs("AWS::CloudFormation::CustomResource", 1);
  template.hasResourceProperties("AWS::CloudFormation::CustomResource", {
    DomainName: "news.example.org",
    Region: "us-east-1",
    HostedZoneId: "Z123456789",
  });
  template.hasResourceProperties("AWS::CloudFront::Distribution", {
    DistributionConfig: Match.objectLike({ Aliases: ["news.example.org"], ViewerCertificate: Match.objectLike({ AcmCertificateArn: Match.anyValue() }) }),
  });
  assert.equal(publication.environment.PAPYRUS_SITE_PUBLIC_URL, "https://news.example.org");
}

{
  const { template } = synthesize({ kind: "s3-projection", edgeDistributionArn: edgeArn, retainBucketOnDelete: false });
  template.hasResource("AWS::S3::Bucket", { DeletionPolicy: "Delete", UpdateReplacePolicy: "Delete" });
  template.hasResourceProperties("Custom::S3AutoDeleteObjects", Match.anyValue());
}

{
  const { template } = synthesize({ kind: "s3-projection" });
  assertSiteBucketIsPrivateAndVersioned(template);
  assert.equal(oacStatements(template).length, 0);
}

assert.throws(() => synthesize({ kind: "s3-projection", edgeDistributionArn: edgeArn, distribution: { create: true } }), /mutually exclusive/);

{
  const app = new App();
  const publicationStack = new Stack(app, "ProjectionQueueStack", { env: { account: "123456789012", region: "us-east-1" } });
  const functionStack = new Stack(app, "ContentActionsStack", { env: { account: "123456789012", region: "us-east-1" } });
  const publication = addS3ProjectionPublication(publicationStack, { kind: "s3-projection" });
  const contentActions = new lambda.Function(functionStack, "ContentActions", {
    runtime: lambda.Runtime.PYTHON_3_12,
    handler: "handler.handler",
    code: lambda.Code.fromInline("def handler(event, context):\n    return {}\n"),
  });
  addProjectionRetries(contentActions, publication.deadLetterQueue);
  const template = Template.fromStack(functionStack);
  template.hasResourceProperties("AWS::Lambda::EventInvokeConfig", {
    MaximumRetryAttempts: 1,
    MaximumEventAgeInSeconds: 3600,
    DestinationConfig: { OnFailure: { Destination: Match.anyValue() } },
  });
  template.hasResourceProperties("AWS::IAM::Policy", {
    PolicyDocument: {
      Statement: [Match.objectLike({ Action: "lambda:InvokeFunction", Effect: "Allow" })],
    },
  });
  const rendered = JSON.stringify(template.toJSON());
  assert.ok(rendered.includes("sqs:SendMessage"), "the function may send failed events to the dead letter queue");
}

console.log("s3-projection publication ok");
