import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";

/**
 * What the function reads and writes with its own role, through the site's own API (`allow.resource(imageService)` in the schema grants query and
 * mutate; the function calls no other service). Today: the doctrine and Story `Item` records it reads by index and the new profile version it writes,
 * the `NewsroomSection` it reads, the `ModelAttachment` row of an example picture it checks before listing it, and the canonical `KnowledgeCorpus` that names the publication. Later build steps add the candidate model and the
 * private storage prefix; each adds its own grant here, and none is granted before its operations exist.
 */
export const IMAGE_SERVICE_FUNCTION_FIELDS = [
  "Query/fields/listKnowledgeCorporaByRoleAndName",
  "Query/fields/itemBySlug",
  "Query/fields/listItemsByLineageAndVersion",
  "Query/fields/getNewsroomSection",
  "Query/fields/getModelAttachment",
  "Query/fields/listNewsroomSections",
  "Mutation/fields/createItem",
  "Mutation/fields/updateItem",
];

/** The function's environment: the site's own API. It holds no secret and calls no provider in this step. */
export function wireImageService(backend: any): void {
  const lambda = backend.imageService.resources.lambda as LambdaFunction;
  lambda.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
}
