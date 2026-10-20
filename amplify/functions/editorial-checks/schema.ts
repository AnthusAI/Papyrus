import { a } from "@aws-amplify/backend";
import { editorialChecks } from "./resource";

const editors = ["editor", "admin"];

/**
 * Core to every site's data API. Policies, settings and editors' decisions live in Papyrus; Limatus checks
 * content against them. Editors read policies and record decisions; admins
 * manage policies and settings. Only the function (IAM) calls Limatus.
 */
export const editorialChecksSchemaDefinitions = {
    EditorialPolicy: a
      .model({
        id: a.id().required(),
        policyKey: a.string().required(),
        scope: a.string().required(),
        version: a.integer().required(),
        title: a.string().required(),
        guidance: a.string().required(),
        severity: a.string().required(),
        enabled: a.boolean().required(),
        detectors: a.json().required(),
        examples: a.json(),
        rewriteGuidance: a.string(),
        source: a.string().required(),
      })
      .disableOperations(["subscriptions"])
      .authorization((allow) => [allow.group("editor").to(["read"]), allow.group("admin")]),
    EditorialCheckSettings: a
      .model({
        id: a.id().required(),
        settings: a.json().required(),
      })
      .disableOperations(["subscriptions"])
      .authorization((allow) => [allow.group("editor").to(["read"]), allow.group("admin")]),
    EditorialFeedback: a
      .model({
        id: a.id().required(),
        itemId: a.string().required(),
        findingId: a.string().required(),
        policyId: a.string().required(),
        detectorId: a.string().required(),
        lane: a.string().required(),
        probability: a.float(),
        decision: a.string().required(),
        reason: a.string(),
        text: a.string(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [index("itemId").queryField("listEditorialFeedbackByItem")])
      .authorization((allow) => [allow.group("editor").to(["create", "read"]), allow.group("admin")]),
    checkEditorial: a
      .query()
      .arguments({ body: a.string().required(), format: a.string(), section: a.string() })
      .returns(a.json())
      .authorization((allow) => [allow.groups(editors)])
      .handler(a.handler.function(editorialChecks)),
    suggestEditorialRewrite: a
      .query()
      .arguments({
        body: a.string().required(),
        format: a.string(),
        section: a.string(),
        finding: a.json(),
        selection: a.json(),
        note: a.string(),
      })
      .returns(a.json())
      .authorization((allow) => [allow.groups(editors)])
      .handler(a.handler.function(editorialChecks)),
    draftEditorialQuestions: a
      .query()
      .arguments({ title: a.string().required(), guidance: a.string().required(), examples: a.json() })
      .returns(a.json())
      .authorization((allow) => [allow.group("admin")])
      .handler(a.handler.function(editorialChecks)),
    tryEditorialPolicy: a
      .query()
      .arguments({ policy: a.json().required(), text: a.string().required(), format: a.string() })
      .returns(a.json())
      .authorization((allow) => [allow.group("admin")])
      .handler(a.handler.function(editorialChecks)),
    importEditorialStarterPack: a
      .mutation()
      .arguments({ name: a.string().required() })
      .returns(a.json())
      .authorization((allow) => [allow.group("admin")])
      .handler(a.handler.function(editorialChecks)),
    recalibrateEditorialPolicies: a
      .mutation()
      .returns(a.json())
      .authorization((allow) => [allow.group("admin")])
      .handler(a.handler.function(editorialChecks)),
  };
