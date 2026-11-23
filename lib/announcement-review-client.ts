/**
 * The console's door to the announcement review of X story posts (PPY-e2829f): `announcements_review_show` and `announcements_review_set`, sent as requests to the
 * site's agent-policy function (`agentPolicyChange`). That function is the only writer of the agent policy and admits only an admin whose token was issued to a
 * person-only app client (the console's), so a credential an agent shares (the command line's) is refused there, and a request that declares an agent is blocked. The
 * browser sends the operation and its input; the function takes who is asking, and the site's tenant, from the signed-in session. See
 * src/papyrus_content/agent_policy/function.py.
 */
import { DEFAULT_REVIEW_REASON, X_STORY_POSTS, type ReviewApproval, type ReviewShown } from "./announcement-review-timing";

export const AGENT_POLICY_CHANGE = "mutation AgentPolicyChange($input: AWSJSON) { agentPolicyChange(input: $input) }";

export type ReviewSetResult = { policyVersion: number; approval: ReviewApproval | null; rung: string; scope: Record<string, string> | null; changed: boolean };

export type AnnouncementReviewApi = {
  show(): Promise<ReviewShown>;
  set(approval: ReviewApproval, reason: string): Promise<ReviewSetResult>;
};

/** What the page sends a GraphQL request through: Amplify's `client.graphql`, or a fake in tests. */
export type ReviewTransport = (request: { query: string; variables: { input: string } }) => Promise<unknown>;

type GraphQLResult = { data?: Record<string, unknown>; errors?: { message?: string; errorType?: string }[] };

/** The function's refusal in words a person reads; its own sentence when it gave one. */
export function reviewRefusalText(code: string, message?: string): string {
  if (message) return message;
  if (code === "human_required") return "Only a person signed in to the newsroom sets this. Nothing was saved.";
  if (code === "not_authorized" || code === "forbidden") return "Only an admin sets how posts are reviewed.";
  return "The review could not be reached. It may not be on this site yet.";
}

export function announcementReviewApi(transport: ReviewTransport): AnnouncementReviewApi {
  const send = async <T>(request: Record<string, unknown>): Promise<T> => {
    let result: GraphQLResult;
    try {
      result = (await transport({ query: AGENT_POLICY_CHANGE, variables: { input: JSON.stringify(request) } })) as GraphQLResult;
    } catch (error) {
      result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
    }
    if (result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`))) throw new Error(reviewRefusalText("forbidden"));
    const raw = result.data?.agentPolicyChange;
    if (result.errors?.length || raw === undefined || raw === null) throw new Error(reviewRefusalText("unavailable"));
    const answer = (typeof raw === "string" ? JSON.parse(raw) : raw) as { ok?: boolean; result?: T; error?: string; message?: string };
    if (!answer || answer.ok !== true || answer.result === undefined) throw new Error(reviewRefusalText(String(answer?.error ?? "unavailable"), answer?.message));
    return answer.result;
  };
  return {
    show: () => send<ReviewShown>({ op: "announcements_review_show", ...X_STORY_POSTS }),
    set: (approval, reason) => send<ReviewSetResult>({ op: "announcements_review_set", approval, ...X_STORY_POSTS, reason: reason.trim() || DEFAULT_REVIEW_REASON }),
  };
}

/** The demo workspace (`?demo=1`) and the local preview: the same answers, in memory, with the publish_auto floor the function holds (nothing is sent anywhere). */
export function createDemoReviewApi(initial: ReviewApproval = "hard"): AnnouncementReviewApi {
  let version = 1;
  let approval: ReviewApproval = initial;
  const rungOf = { hard: "prepare", soft: "publish_soft", none: "publish_auto" } as const;
  return {
    show: async () => ({
      policyVersion: version, approval: "hard", rung: "prepare", overrides: approval === "hard" ? [] : [{ scope: { ...X_STORY_POSTS }, approval, rung: rungOf[approval] }],
      chosen: { approval, rung: rungOf[approval], policy: approval === "hard" ? `publication policy (agent policy version ${version})` : `override: channel x, kind story_published (agent policy version ${version})`, reason: null },
    }),
    set: async (wanted) => {
      if (wanted === "none") {
        throw new Error("announce cannot be set to publish_auto: a hard floor says doubt stops automatic publishing at every rung, and the gate that enforces that floor is not built. Use publish_soft or lower.");
      }
      const changed = wanted !== approval;
      if (changed) { approval = wanted; version += 1; }
      return { policyVersion: version, approval: wanted, rung: rungOf[wanted], scope: { ...X_STORY_POSTS }, changed };
    },
  };
}
