/**
 * IAM statement for the content-actions Lambda's read of the revalidate secret.
 * Pure (no CDK imports) so the policy can be tested without synthesizing.
 * The Lambda reads the parameter through boto3 get_parameters (plural), so the
 * plural action must be granted alongside the singular one.
 */
export const REVALIDATE_SECRET_READ_ACTIONS = ["ssm:GetParameter", "ssm:GetParameters"];

export function revalidateSecretReadStatement(input: {
  partition: string;
  region: string;
  account: string;
  parameterName: string;
}): { actions: string[]; resources: string[] } {
  return {
    actions: REVALIDATE_SECRET_READ_ACTIONS,
    resources: [`arn:${input.partition}:ssm:${input.region}:${input.account}:parameter${input.parameterName}`],
  };
}
