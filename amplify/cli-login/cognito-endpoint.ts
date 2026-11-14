import { Fn, Stack } from "aws-cdk-lib";
import { CfnUserPoolDomain } from "aws-cdk-lib/aws-cognito";

/** The Cognito hosted UI's `/oauth2/authorize` URL for the user pool domain in the auth stack. */
export function cognitoAuthorizeEndpoint(authStack: Stack): string {
  const domains = authStack.node.findAll().filter((construct): construct is CfnUserPoolDomain => construct instanceof CfnUserPoolDomain);
  if (domains.length !== 1) {
    throw new Error(`Expected exactly one Cognito user pool domain in the auth stack, found ${domains.length}`);
  }
  return Fn.join("", ["https://", domains[0].domain, ".auth.", authStack.region, ".amazoncognito.com/oauth2/authorize"]);
}
