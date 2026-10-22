import { Aspects, Stack } from "aws-cdk-lib";
import { CfnPolicy } from "aws-cdk-lib/aws-iam";
import type { IFunction } from "aws-cdk-lib/aws-lambda";

/** Lifecycle/context calls, including the fixed reference registration CLI's provenance operations. */
export const ASSIGNMENT_DATA_FIELDS = [
  "Query/fields/getAssignment",
  "Query/fields/getKnowledgeRawPayload",
  "Query/fields/getProcedureRun",
  "Query/fields/getProcedureVersion",
  "Query/fields/getProcedureDefinition",
  "Query/fields/getModelAttachment",
  "Query/fields/getNewsroomSection",
  "Query/fields/listNewsroomSections",
  "Query/fields/listNewsroomSectionsByTenantAndSortOrder",
  "Query/fields/getKnowledgeCorpus",
  "Query/fields/getKnowledgeImportRun",
  "Query/fields/getReference",
  "Query/fields/getReferenceAttachment",
  "Query/fields/getMessage",
  "Query/fields/getSemanticRelation",
  "Query/fields/getSemanticNode",
  "Query/fields/listReferences",
  "Query/fields/listReferenceAttachments",
  "Query/fields/listSemanticRelations",
  "Query/fields/listKnowledgeCorporaByRoleAndName",
  "Query/fields/listItemsByLineageAndVersion",
  "Query/fields/itemBySlug",
  "Query/fields/itemByTenantSlug",
  "Query/fields/listModelAttachmentsByOwnerRoleAndSortKey",
  "Query/fields/listAssignmentsByQueueStatusAndPriority",
  "Query/fields/listSemanticRelationsByObjectState",
  "Query/fields/listSemanticRelationsBySubjectState",
  "Query/fields/listAssignmentEventsByAssignmentAndCreatedAt",
  "Mutation/fields/createAssignment",
  "Mutation/fields/updateAssignment",
  "Mutation/fields/createAssignmentEvent",
  "Mutation/fields/createProcedureRun",
  "Mutation/fields/updateProcedureRun",
  "Mutation/fields/createKnowledgeCorpus",
  "Mutation/fields/updateKnowledgeCorpus",
  "Mutation/fields/createKnowledgeImportRun",
  "Mutation/fields/updateKnowledgeImportRun",
  "Mutation/fields/createKnowledgeRawPayload",
  "Mutation/fields/updateKnowledgeRawPayload",
  "Mutation/fields/createReference",
  "Mutation/fields/updateReference",
  "Mutation/fields/createReferenceAttachment",
  "Mutation/fields/updateReferenceAttachment",
  "Mutation/fields/createMessage",
  "Mutation/fields/updateMessage",
  "Mutation/fields/createSemanticRelation",
  "Mutation/fields/updateSemanticRelation",
  "Mutation/fields/createSemanticNode",
  "Mutation/fields/updateSemanticNode",
  "Mutation/fields/createModelAttachment",
  "Mutation/fields/updateModelAttachment",
  "Mutation/fields/createModelAttachmentUpload",
  "Mutation/fields/completeModelAttachmentUpload",
  "Mutation/fields/createModelAttachmentDownload",
  "Mutation/fields/updateNewsroomSummary",
] as const;

/** Keep the SDK's generated configuration, replacing only this role's GraphQL grants at synthesis. */
export function scopeAssignmentDataAccess(lambda: IFunction, graphqlApiArn: string): void {
  if (!lambda.role) throw new Error("Assignment function needs an execution role.");
  const roleName = lambda.role.roleName;
  const resources = ASSIGNMENT_DATA_FIELDS.map((field) => `${graphqlApiArn}/types/${field}`);
  Aspects.of(Stack.of(lambda)).add({
    visit(node) {
      if (!(node instanceof CfnPolicy)) return;
      const stack = Stack.of(node);
      const roles = stack.resolve(node.roles) as unknown[] | undefined;
      if (!roles?.some((role) => JSON.stringify(role) === JSON.stringify(stack.resolve(roleName)))) return;
      const document = stack.resolve(node.policyDocument) as { Statement: Array<Record<string, unknown>> };
      document.Statement.forEach((statement, index) => {
        const actions = Array.isArray(statement.Action) ? statement.Action : [statement.Action];
        if (actions.includes("*") || actions.includes("appsync:*")) {
          throw new Error("Unexpected wildcard assignment action; review permissions before synthesis.");
        }
        if (!actions.includes("appsync:GraphQL")) return;
        if (statement.Effect !== "Allow" || actions.length !== 1 || statement.NotResource) {
          throw new Error("Unexpected assignment GraphQL policy; review field scoping before synthesis.");
        }
        node.addPropertyOverride(`PolicyDocument.Statement.${index}.Resource`, resources);
      });
    },
  });
}
