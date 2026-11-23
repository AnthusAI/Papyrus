import { a } from "@aws-amplify/backend";
import { automationView } from "./resource";
import { functionHandler } from "../../data/function-handler";

const editors = ["editor", "admin"];

/**
 * Core to every site's data API. The Automation page reads the automation records, the monitoring
 * trigger rows they link to, and the procedure runs through `automationOverview`, and starts a run
 * through `runAutomation`. Today reads the day's runs through `todayOverview` and takes a run off its attention list through `acknowledgeRun`.
 * All admit editors and admins. AppSync also lets an IAM principal call the
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
  /** Today (PPY-5bcf42): what ran in one day, what it decided to do nothing about, what it cost. Shares the function above; reads by index. */
  todayOverview: a
    .query()
    .arguments({ day: a.string(), timeZone: a.string() })
    .returns(a.json())
    .authorization((allow) => [allow.groups(editors)])
    .handler(functionHandler("automationView", automationView)),
  /** Today (PPY-b6d5ad): Acknowledge a failed run or Settle an Outcome unknown. Takes the run off the attention list and records who and when. */
  acknowledgeRun: a
    .mutation()
    .arguments({ runId: a.string().required() })
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
