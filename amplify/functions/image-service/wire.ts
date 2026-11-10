import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";

/**
 * What the function reads and writes with its own role, through the site's own API (`allow.resource(imageService)` in the schema grants query and
 * mutate; the function calls no other service). Today: the doctrine and Story `Item` records it reads by index and the new profile version it writes,
 * the `NewsroomSection` it reads, and the canonical `KnowledgeCorpus` that names the publication. The guideline operations add the `ModelAttachment` rows
 * that name a document's file (read by owner index, created with the file) and, below, the storage prefix of Item payloads. Later build steps add the
 * candidate model; each adds its own grant here, and none is granted before its operations exist.
 */
export const IMAGE_SERVICE_FUNCTION_FIELDS = [
  "Query/fields/listKnowledgeCorporaByRoleAndName",
  "Query/fields/itemBySlug",
  "Query/fields/listItemsByLineageAndVersion",
  "Query/fields/getNewsroomSection",
  "Query/fields/listNewsroomSections",
  // Guideline documents (PPY-8d41d7): the attachment rows that name each version's file, found by owner and role.
  "Query/fields/listModelAttachmentsByOwnerRoleAndSortKey",
  "Mutation/fields/createItem",
  "Mutation/fields/updateItem",
  "Mutation/fields/createModelAttachment",
];

/** Guideline documents are the only files this function touches: the payloads of Item versions. Nothing else in the bucket is reachable. */
export const IMAGE_SERVICE_BUCKET_PREFIX = "newsroom/payloads/item/";
export const IMAGE_SERVICE_BUCKET_ACTIONS = ["s3:GetObject", "s3:PutObject"];

/** The function's environment: the site's own API. It holds no secret and calls no provider in this step. */
export function wireImageService(backend: any): void {
  const lambda = backend.imageService.resources.lambda as LambdaFunction;
  lambda.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
  // Read and write of the guideline documents, on the payload prefix of Item versions only (the role, not a bucket policy, as the other functions do it,
  // so the storage and data stacks do not depend on each other).
  const bucket = backend.storage.resources.bucket;
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: IMAGE_SERVICE_BUCKET_ACTIONS,
      resources: [`${bucket.bucketArn}/${IMAGE_SERVICE_BUCKET_PREFIX}*`],
    }),
  );
  lambda.addEnvironment("PAPYRUS_MEDIA_BUCKET_NAME", bucket.bucketName);
  lambda.addEnvironment("papyrusMedia_BUCKET_NAME", bucket.bucketName);
}
