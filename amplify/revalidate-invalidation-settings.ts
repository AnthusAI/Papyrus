/**
 * Environment and IAM for purging our CloudFront copies of the paths a Pretext reader revalidated.
 * Pure (no CDK imports) so it can be tested without synthesizing.
 */
export const REVALIDATE_DISTRIBUTION_IDS_ENV = "PAPYRUS_REVALIDATE_DISTRIBUTION_IDS";

const CLOUDFRONT_DISTRIBUTION_ID = /^E[A-Z0-9]{8,}$/;

export function validateRevalidateDistributionIds(ids: unknown, revalidateBaseUrl: string | undefined): string[] {
  if (ids === undefined) return [];
  if (!Array.isArray(ids) || ids.length === 0) return ["revalidateDistributionIds must be a non-empty array of CloudFront distribution ids"];
  const problems: string[] = [];
  for (const id of ids) {
    if (typeof id !== "string" || !CLOUDFRONT_DISTRIBUTION_ID.test(id)) {
      problems.push(`revalidateDistributionIds entry ${JSON.stringify(id)} is not a CloudFront distribution id`);
    }
  }
  if ((revalidateBaseUrl ?? "").trim() === "") problems.push("revalidateDistributionIds requires revalidateBaseUrl");
  return problems;
}

export function revalidateDistributionEnvironment(ids: string[]): Record<string, string> {
  return { [REVALIDATE_DISTRIBUTION_IDS_ENV]: ids.join(",") };
}

export function revalidateInvalidationStatement(input: {
  partition: string;
  account: string;
  distributionIds: string[];
}): { actions: string[]; resources: string[] } {
  return {
    actions: ["cloudfront:CreateInvalidation"],
    resources: input.distributionIds.map((id) => `arn:${input.partition}:cloudfront::${input.account}:distribution/${id}`),
  };
}
