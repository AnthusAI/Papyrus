import { Duration, RemovalPolicy } from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import type { Code } from "aws-cdk-lib/aws-lambda";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import { Effect, PolicyStatement, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import type { Construct } from "constructs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { assertValidPublicationConfig, type PapyrusPublicationConfig } from "../site-backend-config";
import { addRenditionsFunction, type RenditionsFunction } from "./renditions-function";
import { RENDITIONS_FUNCTION_NAME_ENV, type RenditionsPlan } from "./renditions-settings";
import { s3ProjectionEnvironment, s3ProjectionPolicyStatements } from "./s3-projection-settings";

const redirectFunctionSourcePath = resolve(dirname(fileURLToPath(import.meta.url)), "redirect-and-index.js");

export type S3ProjectionPublicationProps = Omit<PapyrusPublicationConfig, "kind"> & { kind?: "s3-projection" };

export type S3ProjectionMedia = {
  mediaBucket: s3.IBucket;
  renditions: RenditionsPlan;
  renditionsCode?: Code;
};

export type S3ProjectionPublication = {
  bucket: s3.Bucket;
  keyValueStore: cloudfront.KeyValueStore;
  redirectFunction: cloudfront.Function;
  deadLetterQueue: sqs.Queue;
  distribution?: cloudfront.Distribution;
  distributionId?: string;
  renditions?: RenditionsFunction;
  environment: Record<string, string>;
  policyStatements: PolicyStatement[];
};

function createSiteBucket(scope: Construct, retainBucketOnDelete: boolean): s3.Bucket {
  return new s3.Bucket(scope, "SiteBucket", {
    versioned: true,
    blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    enforceSSL: true,
    encryption: s3.BucketEncryption.S3_MANAGED,
    lifecycleRules: [{ noncurrentVersionExpiration: Duration.days(90) }],
    removalPolicy: retainBucketOnDelete ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    autoDeleteObjects: !retainBucketOnDelete,
  });
}

function createDnsValidatedCertificate(
  scope: Construct,
  aliases: string[],
  hostedZone: { hostedZoneId: string; hostedZoneName: string },
): acm.ICertificate {
  const zone = route53.HostedZone.fromHostedZoneAttributes(scope, "SiteHostedZone", {
    hostedZoneId: hostedZone.hostedZoneId,
    zoneName: hostedZone.hostedZoneName,
  });
  return new acm.DnsValidatedCertificate(scope, "SiteCertificate", {
    domainName: aliases[0],
    subjectAlternativeNames: aliases.slice(1),
    hostedZone: zone,
    region: "us-east-1",
  });
}

function createDistribution(
  scope: Construct,
  props: S3ProjectionPublicationProps,
  bucket: s3.Bucket,
  redirectFunction: cloudfront.Function,
): cloudfront.Distribution {
  const aliases = props.distribution?.aliases ?? [];
  let certificate: acm.ICertificate | undefined;
  if (aliases.length > 0) {
    certificate = props.distribution?.acm !== undefined
      ? createDnsValidatedCertificate(scope, aliases, props.distribution.acm)
      : acm.Certificate.fromCertificateArn(scope, "SiteCertificate", props.distribution?.certificateArn ?? "");
  }
  return new cloudfront.Distribution(scope, "SiteDistribution", {
    defaultRootObject: "index.html",
    httpVersion: cloudfront.HttpVersion.HTTP2_AND_3,
    enableLogging: false,
    domainNames: aliases.length > 0 ? aliases : undefined,
    certificate,
    defaultBehavior: {
      origin: origins.S3BucketOrigin.withOriginAccessControl(bucket),
      viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      compress: true,
      functionAssociations: [{ function: redirectFunction, eventType: cloudfront.FunctionEventType.VIEWER_REQUEST }],
    },
    errorResponses: [
      { httpStatus: 404, responseHttpStatus: 404, responsePagePath: "/404.html" },
      { httpStatus: 403, responseHttpStatus: 404, responsePagePath: "/404.html" },
    ],
  });
}

export function addS3ProjectionPublication(
  scope: Construct,
  props: S3ProjectionPublicationProps,
  media?: S3ProjectionMedia,
): S3ProjectionPublication {
  assertValidPublicationConfig({ kind: "s3-projection", ...props });
  const bucket = createSiteBucket(scope, props.retainBucketOnDelete !== false);

  const keyValueStore = new cloudfront.KeyValueStore(scope, "RedirectsKeyValueStore");
  const redirectFunction = new cloudfront.Function(scope, "RedirectAndIndexFunction", {
    runtime: cloudfront.FunctionRuntime.JS_2_0,
    code: cloudfront.FunctionCode.fromFile({ filePath: redirectFunctionSourcePath }),
    keyValueStore,
  });
  const deadLetterQueue = new sqs.Queue(scope, "ProjectionDeadLetterQueue", {
    encryption: sqs.QueueEncryption.SQS_MANAGED,
    retentionPeriod: Duration.days(14),
    enforceSSL: true,
  });

  const createsDistribution = props.distribution?.create === true;
  const distribution = createsDistribution ? createDistribution(scope, props, bucket, redirectFunction) : undefined;

  let distributionArn: string | undefined;
  if (distribution !== undefined) {
    distributionArn = distribution.distributionArn;
  } else if (props.edgeDistributionArn !== undefined) {
    distributionArn = props.edgeDistributionArn;
    bucket.addToResourcePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        principals: [new ServicePrincipal("cloudfront.amazonaws.com")],
        actions: ["s3:GetObject"],
        resources: [bucket.arnForObjects("*")],
        conditions: { StringEquals: { "aws:SourceArn": props.edgeDistributionArn } },
      }),
    );
  }

  const renditions = media?.renditions.enabled === true
    ? addRenditionsFunction(scope, { siteBucket: bucket, mediaBucket: media.mediaBucket, siteFiles: media.renditions.siteFiles, code: media.renditionsCode })
    : undefined;

  const settingsInput = {
    bucketName: bucket.bucketName,
    bucketArn: bucket.bucketArn,
    keyValueStoreArn: keyValueStore.keyValueStoreArn,
    deadLetterQueueUrl: deadLetterQueue.queueUrl,
    deadLetterQueueArn: deadLetterQueue.queueArn,
    distributionArn,
    distributionId: distribution?.distributionId,
    publicHostName: distribution !== undefined
      ? (props.distribution?.aliases?.[0] ?? distribution.distributionDomainName)
      : undefined,
    projector: props.projector,
    staticDir: props.staticDir,
  };
  return {
    bucket,
    keyValueStore,
    redirectFunction,
    deadLetterQueue,
    distribution,
    distributionId: distribution?.distributionId,
    renditions,
    environment: {
      ...s3ProjectionEnvironment(settingsInput),
      ...(renditions !== undefined ? { [RENDITIONS_FUNCTION_NAME_ENV]: renditions.function.functionName } : {}),
    },
    policyStatements: s3ProjectionPolicyStatements(settingsInput).map(
      (statement) => new PolicyStatement({ effect: Effect.ALLOW, actions: statement.actions, resources: statement.resources }),
    ),
  };
}
