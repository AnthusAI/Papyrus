import { a } from "@aws-amplify/backend";
import { readerActions } from "./function/resource";
import { functionHandler } from "../../data/function-handler";

/**
 * Staff and IAM only: no guest, API key or reader rule on any model. The reader-actions function writes the
 * tables directly with its own role, and editors may list them; admins may delete. `id` is the lookup key:
 * the siteSubject for a profile, the lowercase handle for a claim, `subjectKey#readerId#dimension` for a vote (`subjectKey#readerId#kind` for a flag; the key is the bare id for items and submissions and `type:id` for the rest) and
 * `sub-<sha256 of the canonical URL>` for a submission (so a canonical URL is one submission).
 */
const staffOnly = (allow: any) => [allow.group("editor").to(["read"]), allow.group("admin").to(["read", "delete"])];

export function readerSteeringSchemaDefinitions() {
  return {
    ReaderProfile: a
      .model({
        id: a.id().required(),
        siteSubject: a.string().required(),
        readerId: a.string().required(),
        handle: a.string(),
        state: a.string().required(),
        karma: a.integer(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [index("readerId").name("profilesByReader").queryField("listReaderProfilesByReader")])
      .authorization(staffOnly),
    ReaderHandle: a
      .model({
        id: a.id().required(),
        readerId: a.string().required(),
      })
      .disableOperations(["subscriptions"])
      .authorization(staffOnly),
    ReaderVote: a
      .model({
        id: a.id().required(),
        subjectKey: a.string().required(),
        subjectType: a.string(),
        readerId: a.string().required(),
        dimension: a.string().required(),
        value: a.integer().required(),
        voterRole: a.string().required(),
      })
      .disableOperations(["subscriptions"])
      .authorization(staffOnly),
    ReaderFlag: a
      .model({
        id: a.id().required(),
        subjectKey: a.string().required(),
        subjectType: a.string().required(),
        readerId: a.string().required(),
        kind: a.string().required(),
        reason: a.string().required(),
        targetKey: a.string(),
        suggestedName: a.string(),
        voterRole: a.string().required(),
        createdAt: a.datetime().required(),
      })
      .disableOperations(["subscriptions"])
      .authorization(staffOnly),
    ReaderComment: a
      .model({
        id: a.id().required(),
        subjectKey: a.string().required(),
        readerId: a.string().required(),
        body: a.string().required(),
        parentId: a.string(),
        ratingContext: a.json(),
        state: a.string().required(),
        signals: a.json(),
        moderation: a.string().required(),
        reportCount: a.integer(),
        reviewedAt: a.datetime(),
        editedAt: a.datetime(),
        deletedAt: a.datetime(),
        createdAt: a.datetime().required(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [index("moderation").sortKeys(["createdAt"]).name("commentsByModeration").queryField("listReaderCommentsByModerationAndCreatedAt")])
      .authorization(staffOnly),
    ReaderSubmission: a
      .model({
        id: a.id().required(),
        canonicalUrl: a.string().required(),
        domain: a.string().required(),
        title: a.string().required(),
        kind: a.string().required(),
        note: a.string(),
        readerId: a.string().required(),
        state: a.string().required(),
        similar: a.string().array(),
        signals: a.json(),
        extractionState: a.string().required(),
        itemId: a.string(),
        moderation: a.string().required(),
        reportCount: a.integer(),
        reviewedAt: a.datetime(),
        createdAt: a.datetime().required(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [
        index("domain").sortKeys(["createdAt"]).name("submissionsByDomain").queryField("listReaderSubmissionsByDomainAndCreatedAt"),
        index("moderation").sortKeys(["createdAt"]).name("submissionsByModeration").queryField("listReaderSubmissionsByModerationAndCreatedAt"),
      ])
      .authorization(staffOnly),
    ReaderReport: a
      .model({
        id: a.id().required(),
        targetType: a.string().required(),
        target: a.string().required(),
        reporterReaderId: a.string().required(),
        reason: a.string().required(),
        state: a.string().required(),
        closedAt: a.datetime(),
        createdAt: a.datetime().required(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [index("target").sortKeys(["createdAt"]).name("reportsByTarget").queryField("listReaderReportsByTargetAndCreatedAt")])
      .authorization(staffOnly),
    ModerationAction: a
      .model({
        id: a.id().required(),
        by: a.string().required(),
        actorSub: a.string().required(),
        action: a.string().required(),
        targetType: a.string().required(),
        target: a.string().required(),
        reason: a.string(),
        fromState: a.string().required(),
        toState: a.string().required(),
        fromModeration: a.string(),
        toModeration: a.string(),
        undoOf: a.string(),
        undoneBy: a.string(),
        at: a.datetime().required(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [index("target").sortKeys(["at"]).name("actionsByTarget").queryField("listModerationActionsByTargetAndAt")])
      .authorization(staffOnly),
    ModerationReceipt: a.customType({
      status: a.string().required(),
      id: a.string(),
      error: a.string(),
      message: a.string(),
    }),
    moderateReader: a
      .mutation()
      .arguments({
        action: a.string().required(),
        targetType: a.string().required(),
        target: a.string().required(),
        reason: a.string(),
        undoOf: a.string(),
      })
      .returns(a.ref("ModerationReceipt"))
      .authorization((allow) => [allow.group("editor"), allow.group("admin")])
      .handler(functionHandler("readerActions", readerActions)),
  };
}
