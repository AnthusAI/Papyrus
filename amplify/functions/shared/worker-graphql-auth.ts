/**
 * A Python function that calls the site's GraphQL API as itself (no signed-in person) names the IAM lane in its
 * environment. The shared client in `src/papyrus_content/graphql_http.py` refuses an unnamed lane and tells the caller
 * to run `papyrus login`, so every such function sets this (PPY-5f119a).
 */
export const WORKER_GRAPHQL_AUTH_ENV = "PAPYRUS_GRAPHQL_AUTH";
export const WORKER_GRAPHQL_AUTH = "iam";
