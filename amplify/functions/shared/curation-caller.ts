import { claimGroups, hasEditorRights } from "../../../lib/staff-groups"

/** Only explicitly configured Cognito clients can take an optional delegation role. */
export const CURATION_CLI_CLIENT_ID_VARIABLE = "CURATION_CLI_CLIENT_ID"
export const CURATION_WEB_CLIENT_ID_VARIABLE = "CURATION_WEB_CLIENT_ID"
export const CURATION_MCP_CLIENT_ID_VARIABLE = "CURATION_MCP_CLIENT_ID"
export type CurationClients = { web: string | null; cli: string | null; mcp: string | null }
export type CurationCaller =
  | { lane: "iam" }
  | { lane: "invalid-identity" }
  | { lane: "cli-session" | "mcp-session" | "newsroom-session" | "unseparated-session" | "unreadable-client-session"; sub: string; groups: string[] }

const UNREADABLE_CLIENT_MESSAGE = "This session's sign-in client could not be read or is not configured, so it cannot be used for curation delegations. Sign in again."

export function curationClientsFromEnvironment(environment: Record<string, string | undefined> = process.env): CurationClients {
  const read = (name: string) => (environment[name] ?? "").trim() || null
  return { web: read(CURATION_WEB_CLIENT_ID_VARIABLE), cli: read(CURATION_CLI_CLIENT_ID_VARIABLE), mcp: read(CURATION_MCP_CLIENT_ID_VARIABLE) }
}

/** Cognito ID tokens use aud; access tokens use client_id, even when they also have a resource audience. */
export function tokenClientId(claims: Record<string, unknown>): string | null {
  const use = claims.token_use
  if (use !== undefined && use !== "id" && use !== "access") return null
  const key = use === "access" ? "client_id" : use === "id" ? "aud" : null
  if (key) {
    const value = claims[key]
    return typeof value === "string" && value.trim() ? value.trim() : null
  }
  const aud = typeof claims.aud === "string" ? claims.aud.trim() : ""
  const client = typeof claims.client_id === "string" ? claims.client_id.trim() : ""
  return aud && client && aud !== client ? null : aud || client || null
}

export function classifyCurationCaller(identity: unknown, clients: CurationClients): CurationCaller {
  if (!identity || typeof identity !== "object") return { lane: "invalid-identity" }
  const candidate = identity as { claims?: unknown; userArn?: unknown; accountId?: unknown }
  if (!("claims" in candidate) && typeof candidate.userArn === "string" && candidate.userArn.trim() && typeof candidate.accountId === "string" && candidate.accountId.trim()) return { lane: "iam" }
  if (!candidate.claims || typeof candidate.claims !== "object" || Array.isArray(candidate.claims)) return { lane: "invalid-identity" }
  const claims = candidate.claims as Record<string, unknown>
  const sub = typeof claims.sub === "string" ? claims.sub.trim() : ""
  if (!sub) return { lane: "invalid-identity" }
  const groups = claimGroups(claims["cognito:groups"])
  const client = tokenClientId(claims)
  if (!client || !clients.web || (clients.mcp !== null && clients.mcp === clients.web)) return { lane: "unreadable-client-session", sub, groups }
  if (client === clients.web) return { lane: !clients.cli || clients.cli === clients.web ? "unseparated-session" : "newsroom-session", sub, groups }
  if (clients.cli && clients.mcp && clients.cli === clients.mcp && client === clients.cli) return { lane: "unreadable-client-session", sub, groups }
  if (clients.cli && clients.cli !== clients.web && client === clients.cli) return { lane: "cli-session", sub, groups }
  if (clients.mcp && clients.mcp !== clients.web && client === clients.mcp) return { lane: "mcp-session", sub, groups }
  return { lane: "unreadable-client-session", sub, groups }
}

export function isDelegationEditor(groups: string[]): boolean {
  return hasEditorRights(groups)
}

/** Asking for a delegation, reading its state, and relaying a decision under it: the agent's routes. */
export function requireDelegationAgent(caller: CurationCaller): void {
  if (caller.lane === "iam") return
  if (caller.lane === "invalid-identity") throw new Error("A verified caller identity is required.")
  if (caller.lane === "mcp-session") throw new Error("Agent delegation is not available for this client.")
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
  if (caller.lane === "iam" || caller.lane === "invalid-identity") throw new Error("Only a person signed in to the Newsroom can manage curation delegations.")
  if (caller.lane === "unreadable-client-session") throw new Error(UNREADABLE_CLIENT_MESSAGE)
  if (caller.lane === "mcp-session") throw new Error("A delegation must be approved by a person in the Newsroom, not an agent client.")
  if (caller.lane === "cli-session") {
    throw new Error("A delegation is approved by a person in the Newsroom, not from the CLI session that asked for it.")
  }
  if (!isDelegationEditor(caller.groups)) throw new Error("Only an editor or administrator can manage curation delegations.")
  return { sub: caller.sub, groups: caller.groups }
}

/** Denying and revoking only reduce what an agent may do, so the CLI session that asked may do them too. */
export function requireDelegationWithdrawer(caller: CurationCaller): { sub: string; groups: string[] } {
  if (caller.lane === "iam" || caller.lane === "invalid-identity") throw new Error("Only a person signed in to the Newsroom can manage curation delegations.")
  if (caller.lane === "unreadable-client-session" || caller.lane === "mcp-session") throw new Error(UNREADABLE_CLIENT_MESSAGE)
  if (!isDelegationEditor(caller.groups)) throw new Error("Only an editor or administrator can manage curation delegations.")
  return { sub: caller.sub, groups: caller.groups }
}
