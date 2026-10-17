import { CfnWebACL, CfnWebACLAssociation } from "aws-cdk-lib/aws-wafv2";
import type { Construct } from "constructs";

export const SIGNUP_MUTATION_FIELD = "submitSignup";
export const WAF_MINIMUM_RATE_LIMIT = 10;
export const WAF_EVALUATION_WINDOW_SECONDS = 60;

/**
 * A regional web ACL on the AppSync API with one rate-based rule: more than `limit`
 * submitSignup requests from one address in a minute are blocked with a 429 before
 * the function runs. Only requests whose body names the mutation count, so reads,
 * newsroom saves and CLI imports from the same address are never limited.
 */
export function addSignupRateLimit(scope: Construct, input: { graphqlApiArn: string; limit: number }): CfnWebACL {
  if (!Number.isInteger(input.limit) || input.limit < WAF_MINIMUM_RATE_LIMIT) {
    throw new Error(`signup waf rate limit must be an integer of at least ${WAF_MINIMUM_RATE_LIMIT} (AWS WAF minimum)`);
  }
  const acl = new CfnWebACL(scope, "PapyrusSignupWebAcl", {
    scope: "REGIONAL",
    defaultAction: { allow: {} },
    visibilityConfig: { cloudWatchMetricsEnabled: true, metricName: "PapyrusSignupWebAcl", sampledRequestsEnabled: true },
    rules: [
      {
        name: "SignupRateLimitPerAddress",
        priority: 0,
        action: { block: { customResponse: { responseCode: 429 } } },
        visibilityConfig: { cloudWatchMetricsEnabled: true, metricName: "SignupRateLimitPerAddress", sampledRequestsEnabled: true },
        statement: {
          rateBasedStatement: {
            limit: input.limit,
            evaluationWindowSec: WAF_EVALUATION_WINDOW_SECONDS,
            aggregateKeyType: "IP",
            scopeDownStatement: {
              byteMatchStatement: {
                searchString: SIGNUP_MUTATION_FIELD,
                positionalConstraint: "CONTAINS",
                fieldToMatch: { body: { oversizeHandling: "NO_MATCH" } },
                textTransformations: [{ priority: 0, type: "NONE" }],
              },
            },
          },
        },
      },
    ],
  });
  new CfnWebACLAssociation(scope, "PapyrusSignupWebAclAssociation", {
    resourceArn: input.graphqlApiArn,
    webAclArn: acl.attrArn,
  });
  return acl;
}
