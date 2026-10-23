import { a } from "@aws-amplify/backend";
import { editorialChecks } from "./resource";
import { functionHandler } from "../shared/function-handler";

const editors = ["editor", "admin"];

/**
 * Core to every site's data API. Policies, settings and editors' decisions live in Papyrus; Humanus checks
 * content against them. Editors read policies and record decisions; admins
 * manage policies and settings. Only the function (IAM) calls Humanus.
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
    EditorialCheckRun: a
      .model({
        id: a.id().required(),
        itemId: a.string().required(),
        lineageId: a.string().required(),
        versionNumber: a.integer().required(),
        section: a.string(),
        contentHash: a.string(),
        packVersion: a.string(),
        violations: a.integer().required(),
        reviews: a.integer().required(),
        findings: a.json().required(),
        lanes: a.json(),
        checkedAt: a.datetime().required(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [index("lineageId").sortKeys(["versionNumber"]).queryField("listEditorialCheckRunsByLineage")])
      .authorization((allow) => [allow.group("editor").to(["read"]), allow.group("admin")]),
    listEditorialStarterPacks: a
      .query()
      .returns(a.json())
      .authorization((allow) => [allow.groups(editors)])
      .handler(functionHandler("editorialChecks", editorialChecks)),
    checkItemVersion: a
      .mutation()
      .arguments({ itemId: a.id().required() })
      .returns(a.json())
      .authorization((allow) => [allow.groups(editors)])
      .handler(functionHandler("editorialChecks", editorialChecks)),
    checkEditorial: a
      .query()
      .arguments({ body: a.string().required(), format: a.string(), section: a.string() })
      .returns(a.json())
      .authorization((allow) => [allow.groups(editors)])
      .handler(functionHandler("editorialChecks", editorialChecks)),
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
      .handler(functionHandler("editorialChecks", editorialChecks)),
    draftEditorialQuestions: a
      .query()
      .arguments({ title: a.string().required(), guidance: a.string().required(), examples: a.json() })
      .returns(a.json())
      .authorization((allow) => [allow.group("admin")])
      .handler(functionHandler("editorialChecks", editorialChecks)),
    tryEditorialPolicy: a
      .query()
      .arguments({ policy: a.json().required(), text: a.string().required(), format: a.string() })
      .returns(a.json())
      .authorization((allow) => [allow.group("admin")])
      .handler(functionHandler("editorialChecks", editorialChecks)),
    importEditorialStarterPack: a
      .mutation()
      .arguments({ name: a.string().required() })
      .returns(a.json())
      .authorization((allow) => [allow.group("admin")])
      .handler(functionHandler("editorialChecks", editorialChecks)),
    recalibrateEditorialPolicies: a
      .mutation()
      .returns(a.json())
      .authorization((allow) => [allow.group("admin")])
      .handler(functionHandler("editorialChecks", editorialChecks)),
  };
