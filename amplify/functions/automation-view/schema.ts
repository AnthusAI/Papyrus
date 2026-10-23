import { a } from "@aws-amplify/backend";
import { automationView } from "./resource";
import { functionHandler } from "../shared/function-handler";

const editors = ["editor", "admin"];

/**
 * Core to every site's data API. The Automation page reads the automation records, the monitoring
 * trigger rows they link to, and the procedure runs through `automationOverview`, and starts a run
 * through `runAutomation`. Both admit editors and admins. AppSync also lets an IAM principal call the
 * query when its own policy allows the field (every operation in this schema accepts IAM callers for
 * the functions that call it); the function reads only for an IAM principal of its own account and refuses
 * every IAM caller on `runAutomation`.
 */
export const automationViewSchemaDefinitions = {
  automationOverview: a
    .query()
    .arguments({ automationId: a.string() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("automationView", automationView)),
  runAutomation: a
    .mutation()
    .arguments({ automationId: a.string().required(), input: a.json() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("automationView", automationView)),
};
