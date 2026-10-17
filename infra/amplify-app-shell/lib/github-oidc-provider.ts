import { Construct } from "constructs";
import { CfnOutput, Stack, StackProps } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";

export const GITHUB_OIDC_PROVIDER_HOST = "token.actions.githubusercontent.com";

/**
 * Account-global singleton: AWS allows one IAM OIDC provider per issuer URL per
 * account, so this never belongs in a per-site stack. Deploy it once per
 * account, and only after `aws iam list-open-id-connect-providers` shows no
 * provider for token.actions.githubusercontent.com. When one already exists,
 * do not deploy this stack: per-site CI roles only reference the provider by
 * its ARN (arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com)
 * and work against an existing provider unchanged.
 */
export class GithubOidcProviderStack extends Stack {
  public readonly providerArn: string;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const provider = new iam.OpenIdConnectProvider(this, "GithubOidc", {
      url: `https://${GITHUB_OIDC_PROVIDER_HOST}`,
      clientIds: ["sts.amazonaws.com"],
    });

    this.providerArn = provider.openIdConnectProviderArn;
    new CfnOutput(this, "GithubOidcProviderArn", { value: provider.openIdConnectProviderArn });
  }
}
