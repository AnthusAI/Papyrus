import { a } from "@aws-amplify/backend";

/**
 * Staff and IAM only: no guest, API key or reader rule on any model. The reader-actions function writes the
 * tables directly with its own role, and editors may list them; admins may delete. `id` is the lookup key:
 * the siteSubject for a profile, the lowercase handle for a claim and `subjectKey#readerId#dimension` for a vote.
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
  };
}
