import { a } from "@aws-amplify/backend";
import { monitoringView } from "./resource";
import { functionHandler } from "../../data/function-handler";

const editors = ["editor", "admin"];

/**
 * Core to every site's data API. The Monitoring page reads the shared monitoring pipeline through
 * this one query. AppSync admits editors and admins only; the function checks the groups again,
 * and returns the whole shared pipeline to admins alone.
 */
export const monitoringViewSchemaDefinitions = {
  monitoringOverview: a
    .query()
    .arguments({ scope: a.string() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("monitoringView", monitoringView)),
  monitoringEmailSubmission: a
    .query()
    .arguments({ receiptId: a.string().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("monitoringView", monitoringView)),
  monitoringResolveEmailArticleLink: a
    .mutation()
    .arguments({ receiptId: a.string().required(), candidateIndex: a.integer().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("monitoringView", monitoringView)),
};
