import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { Code } from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import { addS3ProjectionPublication } from "../amplify/publication/s3-projection";
import {
  RENDITIONS_FUNCTION_NAME_ENV,
  planRenditions,
  renditionsEnvironment,
  renditionsEventPattern,
} from "../amplify/publication/renditions-settings";

const siteRoot = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-renditions-plan-"));
try {
  fs.mkdirSync(path.join(siteRoot, "with-images"));
  fs.mkdirSync(path.join(siteRoot, "without-images"));
  fs.mkdirSync(path.join(siteRoot, "no-settings"));
  fs.writeFileSync(path.join(siteRoot, "with-images/projection.json"), JSON.stringify({ images: { gatsby_parity: true } }));
  fs.writeFileSync(path.join(siteRoot, "without-images/projection.json"), JSON.stringify({ theme: "hackerman" }));
  fs.mkdirSync(path.join(siteRoot, "with-originals"));
  fs.writeFileSync(path.join(siteRoot, "with-originals/projection.json"), JSON.stringify({ media: { originals: true } }));

  assert.deepEqual(planRenditions(undefined, siteRoot), { enabled: false, siteFiles: [] });
  assert.deepEqual(planRenditions({}, siteRoot), { enabled: false, siteFiles: [] });
  assert.deepEqual(planRenditions({ staticDir: "no-settings" }, siteRoot), { enabled: false, siteFiles: [] });
  assert.deepEqual(planRenditions({ staticDir: "without-images" }, siteRoot), { enabled: false, siteFiles: [] });
  assert.deepEqual(planRenditions({ staticDir: "with-originals" }, siteRoot), {
    enabled: true,
    siteFiles: [{ from: "with-originals/projection.json", to: "site_static/projection.json" }],
  });
  assert.deepEqual(planRenditions({ staticDir: "with-images" }, siteRoot), {
    enabled: true,
    siteFiles: [{ from: "with-images/projection.json", to: "site_static/projection.json" }],
  });
} finally {
  fs.rmSync(siteRoot, { recursive: true, force: true });
}

assert.deepEqual(renditionsEnvironment("site-bucket"), {
  PAPYRUS_SITE_BUCKET: "site-bucket",
  PAPYRUS_SITE_STATIC_DIR: "/var/task/site_static",
});
assert.deepEqual(renditionsEventPattern("media-bucket"), {
  source: ["aws.s3"],
  detailType: ["Object Created"],
  detail: { bucket: { name: ["media-bucket"] }, object: { key: [{ prefix: "media/" }] } },
});

function synthesize(withRenditions: boolean) {
  const app = new App();
  const stack = new Stack(app, "RenditionsHarness", { env: { account: "123456789012", region: "us-east-1" } });
  const mediaBucket = new s3.Bucket(stack, "MediaBucket");
  const publication = addS3ProjectionPublication(
    stack,
    { staticDir: "web/static" },
    withRenditions
      ? {
          mediaBucket,
          renditions: { enabled: true, siteFiles: [] },
          renditionsCode: Code.fromInline("def handler(event, context): return {}"),
        }
      : { mediaBucket, renditions: { enabled: false, siteFiles: [] } },
  );
  return { template: Template.fromStack(stack), publication };
}

const without = synthesize(false);
without.template.resourceCountIs("AWS::Lambda::Function", 0);
without.template.resourceCountIs("AWS::Events::Rule", 0);
assert.equal(without.publication.renditions, undefined);
assert.equal(RENDITIONS_FUNCTION_NAME_ENV in without.publication.environment, false);

const { template, publication } = synthesize(true);
template.resourceCountIs("AWS::Lambda::Function", 1);
template.hasResourceProperties("AWS::Lambda::Function", {
  Runtime: "python3.12",
  Architectures: ["arm64"],
  Handler: "handler.handler",
  MemorySize: 3008,
  Timeout: 300,
  EphemeralStorage: { Size: 2048 },
  Environment: { Variables: { PAPYRUS_SITE_BUCKET: Match.anyValue(), PAPYRUS_SITE_STATIC_DIR: "/var/task/site_static" } },
  DeadLetterConfig: Match.objectLike({ TargetArn: Match.anyValue() }),
});
template.hasResourceProperties("AWS::Lambda::EventInvokeConfig", { MaximumRetryAttempts: 2 });
template.hasResourceProperties("AWS::Events::Rule", {
  EventPattern: {
    source: ["aws.s3"],
    "detail-type": ["Object Created"],
    detail: { bucket: { name: [Match.anyValue()] }, object: { key: [{ prefix: "media/" }] } },
  },
  Targets: [Match.objectLike({ Arn: Match.anyValue(), RetryPolicy: { MaximumRetryAttempts: 2 } })],
});
assert.ok(RENDITIONS_FUNCTION_NAME_ENV in publication.environment);

const functionRoleStatements = Object.values(template.findResources("AWS::IAM::Policy"))
  .flatMap((policy) => policy.Properties.PolicyDocument.Statement as Array<{ Action: string | string[]; Effect: string }>)
  .filter((statement) => statement.Effect === "Allow");
const actions = functionRoleStatements.flatMap((statement) => (Array.isArray(statement.Action) ? statement.Action : [statement.Action]));
assert.ok(actions.includes("s3:GetObject") && actions.includes("s3:PutObject"));
assert.ok(actions.includes("s3:ListBucket"), "a missing description must read as absent (404), not as access denied");
assert.equal(actions.includes("s3:DeleteObject"), false, "the renditions function never deletes");
