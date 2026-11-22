import { a } from "@aws-amplify/backend";
import { agentPolicy } from "./resource";
import { functionHandler } from "../../data/function-handler";

/**
 * The one way a signed-in admin changes the agent policy: this mutation. The function checks that the token was issued to a person-only app client, so a credential an
 * agent shares with the person (the CLI's) is refused. The admin group no longer holds the S3 write on the policy document (amplify/agents/admin-policy-grant.ts).
 */
export const agentPolicySchemaDefinitions = {
  agentPolicyChange: a
    .mutation()
    .arguments({ input: a.json() })
    .returns(a.json())
    .authorization((allow) => [allow.group("admin")])
    .handler(functionHandler("agentPolicy", agentPolicy)),
};
