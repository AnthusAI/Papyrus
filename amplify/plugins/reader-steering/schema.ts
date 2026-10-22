import { a } from "@aws-amplify/backend";

/**
 * Staff and IAM only: no guest, API key or reader rule on any model. The reader-actions function writes the
 * tables directly with its own role, and editors may list them; admins may delete. `id` is the lookup key:
 * the siteSubject for a profile, the lowercase handle for a claim, `subjectKey#readerId#dimension` for a vote and
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
        readerId: a.string().required(),
        dimension: a.string().required(),
        value: a.integer().required(),
        voterRole: a.string().required(),
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
        reviewedAt: a.datetime(),
        editedAt: a.datetime(),
        deletedAt: a.datetime(),
        createdAt: a.datetime().required(),
      })
      .disableOperations(["subscriptions"])
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
        reviewedAt: a.datetime(),
        createdAt: a.datetime().required(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [index("domain").sortKeys(["createdAt"]).name("submissionsByDomain").queryField("listReaderSubmissionsByDomainAndCreatedAt")])
      .authorization(staffOnly),
  };
}
