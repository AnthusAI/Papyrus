import { claimGroups, hasEditorRights } from "../../../lib/staff-groups"

/**
 * Who is calling, and which delegation routes they may use. Delegation is optional: an agent normally accepts, rejects and rates directly through
 * the signed-in editor's session as that person, and the lane here is only a plain note of where the action came from (`edit-origin.ts`), never
 * a gate on those direct decisions. The rules below apply to the optional delegation routes only.
 *
 * A delegation is the editor's permission for an agent to relay their accept, reject and star decisions. The approval of the request must come
 * from a person in the Newsroom, never from the agent that asked. On the signed-in CLI lane the agent works inside the editor's own session,
 * so the gate cannot be "who is signed in": it is the Cognito app client the token was issued to. The CLI signs in on its own client
 * (`cliOnFederationClient`), the Newsroom on the web client, and Cognito signs the token's `aud` (ID token) or `client_id` (access token).
 * A token for the CLI client can ask for a delegation and relay a decision under one; only a token for another client can approve, deny or
 * create one.
 *
 * `CURATION_CLI_CLIENT_ID` names the CLI client. A backend that has not separated the CLI from the Newsroom has no such id, so a signed-in
 * session there cannot ask for a delegation or relay with one: the lane fails closed rather than letting a session approve its own request.
 */
export const CURATION_CLI_CLIENT_ID_VARIABLE = "CURATION_CLI_CLIENT_ID"

export type CurationCaller =
  /** An operator on AWS credentials (identity pool role): no person is signed in. The lane the agent routes used before the signed-in lane. */
  | { lane: "iam" }
  /** A person's token issued to the CLI client. */
  | { lane: "cli-session"; sub: string; groups: string[] }
  /** A person's token issued to any other client: the Newsroom. */
  | { lane: "newsroom-session"; sub: string; groups: string[] }
  /** A person's token on a backend that has not named a CLI client, so the Newsroom and the CLI cannot be told apart. */
  | { lane: "unseparated-session"; sub: string; groups: string[] }
  /** A token whose client cannot be read (no aud or client_id): neither the CLI nor provably the Newsroom, so it can do nothing here. */
  | { lane: "unreadable-client-session"; sub: string; groups: string[] }

const UNREADABLE_CLIENT_MESSAGE = "This session's sign-in client could not be read, so it cannot be used for curation delegations. Sign in again."

export function cliClientIdFromEnvironment(environment: Record<string, string | undefined> = process.env): string | null {
  const value = (environment[CURATION_CLI_CLIENT_ID_VARIABLE] ?? "").trim()
  return value === "" ? null : value
}

/** The Cognito app client a token was issued to: `aud` on an ID token, `client_id` on an access token. */
export function tokenClientId(claims: Record<string, unknown>): string | null {
  for (const key of ["aud", "client_id"]) {
    const value = claims[key]
    if (typeof value === "string" && value.trim() !== "") return value.trim()
  }
  return null
}

export function classifyCurationCaller(identity: unknown, cliClientId: string | null): CurationCaller {
  const claims = (identity as { claims?: Record<string, unknown> } | null | undefined)?.claims ?? {}
  const sub = typeof claims.sub === "string" ? claims.sub.trim() : ""
  if (!sub) return { lane: "iam" }
  const groups = claimGroups(claims["cognito:groups"])
  if (!cliClientId) return { lane: "unseparated-session", sub, groups }
  const client = tokenClientId(claims)
  if (!client) return { lane: "unreadable-client-session", sub, groups }
  return { lane: client === cliClientId ? "cli-session" : "newsroom-session", sub, groups }
}

export function isDelegationEditor(groups: string[]): boolean {
  return hasEditorRights(groups)
}

/** Asking for a delegation, reading its state, and relaying a decision under it: the agent's routes. */
export function requireDelegationAgent(caller: CurationCaller): void {
  if (caller.lane === "iam") return
  if (caller.lane === "cli-session") {
    if (!isDelegationEditor(caller.groups)) throw new Error("Only an editor or administrator can ask for or use a curation delegation.")
    return
  }
  if (caller.lane === "unseparated-session") {
    throw new Error(
      "This site does not sign the CLI in on its own client, so a signed-in session could approve its own delegation request. "
      + "Turn on cliOnFederationClient for the site, then sign in again with papyrus login.",
    )
  }
  if (caller.lane === "unreadable-client-session") throw new Error(UNREADABLE_CLIENT_MESSAGE)
  throw new Error("Ask for a delegation from the CLI. The Newsroom approves requests; it does not make them.")
}

/** Approving, denying (with a code), creating and listing: the person's routes in the Newsroom. */
export function requireDelegationApprover(caller: CurationCaller): { sub: string; groups: string[] } {
  if (caller.lane === "iam") throw new Error("Only a person signed in to the Newsroom can manage curation delegations.")
  if (caller.lane === "unreadable-client-session") throw new Error(UNREADABLE_CLIENT_MESSAGE)
  if (caller.lane === "cli-session") {
    throw new Error("A delegation is approved by a person in the Newsroom, not from the CLI session that asked for it.")
  }
  if (!isDelegationEditor(caller.groups)) throw new Error("Only an editor or administrator can manage curation delegations.")
  return { sub: caller.sub, groups: caller.groups }
}

/** Denying and revoking only reduce what an agent may do, so the CLI session that asked may do them too. */
export function requireDelegationWithdrawer(caller: CurationCaller): { sub: string; groups: string[] } {
  if (caller.lane === "iam") throw new Error("Only a person signed in to the Newsroom can manage curation delegations.")
  if (caller.lane === "unreadable-client-session") throw new Error(UNREADABLE_CLIENT_MESSAGE)
  if (!isDelegationEditor(caller.groups)) throw new Error("Only an editor or administrator can manage curation delegations.")
  return { sub: caller.sub, groups: caller.groups }
}
