import { a } from "@aws-amplify/backend";
import { automationView } from "./resource";

const editors = ["editor", "admin"];

/**
 * Core to every site's data API. The Automation page reads the automation records, the monitoring
 * trigger rows they link to, and the procedure runs through this one query. AppSync admits editors
 * and admins only; the function checks the groups again.
 */
export const automationViewSchemaDefinitions = {
  automationOverview: a
    .query()
    .arguments({ automationId: a.string() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(a.handler.function(automationView)),
};
