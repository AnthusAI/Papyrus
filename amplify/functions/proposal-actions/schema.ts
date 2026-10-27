import { a } from "@aws-amplify/backend";
import { proposalActions } from "./resource";
import { functionHandler } from "../../data/function-handler";

/**
 * Core to every site's data API (editors and operators only; nothing here is reader-facing). Editors may list proposals;
 * admins may also delete. The proposal-actions function writes the table with its own role. The reader-steering plugin
 * builds on this model: it reads the table to take reader votes on proposals and to publish them in its snapshot.
 */
const staffOnly = (allow: any) => [allow.group("editor").to(["read"]), allow.group("admin").to(["read", "delete"])];

export const proposalActionsSchemaDefinitions = {
  Proposal: a
    .model({
      id: a.id().required(),
      kind: a.string().required(),
      title: a.string().required(),
      summary: a.string(),
      body: a.string().required(),
      targets: a.json().required(),
      evidence: a.json(),
      proposer: a.string().required(),
      state: a.string().required(),
      history: a.json().required(),
      communityResult: a.json(),
      pinned: a.boolean(),
      held: a.boolean(),
      override: a.json(),
      exclusions: a.json(),
      editorLog: a.json(),
      needsLook: a.json(),
      createdAt: a.datetime().required(),
    })
    .disableOperations(["subscriptions"])
    .secondaryIndexes((index) => [index("state").sortKeys(["createdAt"]).name("proposalsByState").queryField("listProposalsByStateAndCreatedAt")])
    .authorization(staffOnly),
  ProposalReceipt: a.customType({
    status: a.string().required(),
    id: a.string(),
    error: a.string(),
    message: a.string(),
  }),
  // What an operator may read of a story draft: these six fields and nothing else (no body, evidence, history, proposer, vote or log).
  StoryDraftSummary: a.customType({
    id: a.string().required(),
    title: a.string().required(),
    summary: a.string(),
    targets: a.json(),
    state: a.string().required(),
    createdAt: a.string().required(),
  }),
  StoryDraftList: a.customType({
    status: a.string().required(),
    id: a.string(),
    error: a.string(),
    message: a.string(),
    drafts: a.ref("StoryDraftSummary").array(),
  }),
  // Editors and admins file as themselves. AppSync also admits an IAM principal whose own policy allows the field (the
  // schema accepts IAM callers for the functions that call it); the function files an AI proposal for an IAM principal
  // of its own account only, and refuses an identity-pool user and any other account. No IAM rule is declared here.
  fileProposal: a
    .mutation()
    .arguments({
      kind: a.string().required(),
      title: a.string().required(),
      body: a.string().required(),
      summary: a.string(),
      targets: a.json(),
      evidence: a.json(),
    })
    .returns(a.ref("ProposalReceipt"))
    .authorization((allow) => [allow.group("editor"), allow.group("admin")])
    .handler(functionHandler("proposalActions", proposalActions)),
  // The same IAM rule as fileProposal, narrower: an operator may move only draft to in_steering or declined.
  // Approving, deciding after review and overriding are refused for IAM in the function (`operator_not_allowed`).
  transitionProposal: a
    .mutation()
    .arguments({
      proposalId: a.string().required(),
      state: a.string().required(),
      reason: a.string(),
      result: a.string(),
    })
    .returns(a.ref("ProposalReceipt"))
    .authorization((allow) => [allow.group("editor"), allow.group("admin")])
    .handler(functionHandler("proposalActions", proposalActions)),
  // Read only, and the same caller rule as fileProposal: editors and admins, or an IAM principal of the function's own account. The function
  // answers the story drafts' id, title, summary, targets, state and createdAt so an unattended run can dedupe; nothing else.
  listStoryDrafts: a
    .query()
    .returns(a.ref("StoryDraftList"))
    .authorization((allow) => [allow.group("editor"), allow.group("admin")])
    .handler(functionHandler("proposalActions", proposalActions)),
  // Editors and admins only, and the function refuses an IAM operator: pin, unpin, hold, release, exclude_votes and
  // undo_exclusion. `rule` is a batch rule for exclude_votes; `exclusionId` names the exclusion undo_exclusion reverses.
  editProposal: a
    .mutation()
    .arguments({
      proposalId: a.string().required(),
      action: a.string().required(),
      rule: a.string(),
      exclusionId: a.string(),
    })
    .returns(a.ref("ProposalReceipt"))
    .authorization((allow) => [allow.group("editor"), allow.group("admin")])
    .handler(functionHandler("proposalActions", proposalActions)),
};
