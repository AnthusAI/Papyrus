/**
 * A function reaches its site's GraphQL API as itself, signed with its own role: the operator lane. The Papyrus engine's
 * default lane is a signed-in person (`papyrus login`), and it never falls back to AWS credentials on its own (PPY-5f119a),
 * so the endpoint and the lane always travel together. Give a function the endpoint only through these.
 */
export const OPERATOR_LANE = { PAPYRUS_GRAPHQL_AUTH: "iam" } as const;

export function siteApiEnvironment(graphqlEndpoint: string): Record<string, string> {
  return { PAPYRUS_GRAPHQL_ENDPOINT: graphqlEndpoint, ...OPERATOR_LANE };
}

export function connectToSiteApi(target: { addEnvironment(name: string, value: string): unknown }, graphqlEndpoint: string): void {
  for (const [name, value] of Object.entries(siteApiEnvironment(graphqlEndpoint))) target.addEnvironment(name, value);
}
