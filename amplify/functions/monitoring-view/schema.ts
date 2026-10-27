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
  // One more page of one Monitoring list (runs, routerRuns, items, emailSubmissions), after a cursor from
  // the overview or a previous page. filter "held" lists only held email submissions, restarting from the newest.
  monitoringPage: a
    .query()
    .arguments({ list: a.string().required(), cursor: a.string(), filter: a.string(), scope: a.string() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("monitoringView", monitoringView)),
  monitoringEmailSubmission: a
    .query()
    .arguments({ receiptId: a.string().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("monitoringView", monitoringView)),
  monitoringQueueEmailReference: a
    .mutation()
    .arguments({ input: a.json().required() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("monitoringView", monitoringView)),
  // Accept ("release") or Reject ("discard") one held email submission. The function validates the
  // signed-in editor and that the message is routed to this publication; the receiver applies it.
  monitoringDecideEmailSubmission: a
    .mutation()
    .arguments({ receiptId: a.string().required(), decision: a.string().required(), reason: a.string() })
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
