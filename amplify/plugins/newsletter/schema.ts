import { a } from "@aws-amplify/backend";
import { newsletterOps } from "./ops/resource";

const staff = ["editor", "admin"];
const admins = ["admin"];

/** The newsroom's newsletter operations, all JSON in and out. The function checks the groups again from the identity claims. */
export const NEWSLETTER_QUERIES = ["newsletterIssues", "newsletterIssue", "newsletterPreview"];
export const NEWSLETTER_MUTATIONS = [
  "newsletterApproveIssue",
  "newsletterCancelIssue",
  "newsletterStopIssue",
  "newsletterTestSend",
  "newsletterCreateDraft",
];
/** Who AppSync admits to each operation. Approve, cancel and stop are admin only; everything else is editors and admins. */
export const NEWSLETTER_OPERATION_GROUPS: Record<string, string[]> = {
  newsletterIssues: staff,
  newsletterIssue: staff,
  newsletterPreview: staff,
  newsletterTestSend: staff,
  newsletterCreateDraft: staff,
  newsletterApproveIssue: admins,
  newsletterCancelIssue: admins,
  newsletterStopIssue: admins,
};

/**
 * The newsletter plugin adds no GraphQL model: subscriber records are personal data kept in the plugin's own DynamoDB
 * table, never readable through the content API. It adds eight operations for the newsroom's Newsletter panel.
 */
export function newsletterSchemaDefinitions(): Record<string, unknown> {
  const handler = a.handler.function(newsletterOps);
  const query = (name: string) =>
    a.query().arguments({ input: a.json() }).returns(a.json()).authorization((allow) => [allow.groups(NEWSLETTER_OPERATION_GROUPS[name])]).handler(handler);
  const mutation = (name: string) =>
    a.mutation().arguments({ input: a.json() }).returns(a.json()).authorization((allow) => [allow.groups(NEWSLETTER_OPERATION_GROUPS[name])]).handler(handler);
  return {
    ...Object.fromEntries(NEWSLETTER_QUERIES.map((name) => [name, query(name)])),
    ...Object.fromEntries(NEWSLETTER_MUTATIONS.map((name) => [name, mutation(name)])),
  };
}
