import { classifyCurationCaller, curationClientsFromEnvironment, type CurationCaller, type CurationClients } from "./curation-caller"

/**
 * Where an editor's decision was made, written on the record it changes so a later reader can tell them apart.
 *
 * A person may make these decisions from the CLI as well as in the Newsroom (concept names, descriptions, links between concepts), so the CLI is not
 * refused. But a record of "an editor accepted this" must not read as if the editor did it in the Newsroom when it was done through the CLI, where a
 * script or an agent may be working in the editor's own session. The origin comes from the token's app client (`curation-caller.ts`), never from
 * anything the caller sends:
 *
 * - `cli`: a session on the CLI client.
 * - `newsroom`: a session on the configured web client.
 * - `signed-in`: a person's session on a site that has not named a CLI client, so the two cannot be told apart.
 * - `operator`: an explicitly identified AWS credentials caller.
 * - `signed-in` also covers unknown, unreadable or agent clients, and invalid identities.
 *
 * The origin is a plain note, never a gate: a signed-in editor or admin decides as themselves from the CLI or the Newsroom, and an agent working
 * through their session acts for them.
 */
export type EditOrigin = "cli" | "newsroom" | "signed-in" | "operator"

export function editOriginOf(caller: CurationCaller): EditOrigin {
  // A session whose sign-in client cannot be read is still a signed-in person; `via` is a note, never a gate.
  if (caller.lane === "unreadable-client-session" || caller.lane === "mcp-session" || caller.lane === "invalid-identity") return "signed-in"
  if (caller.lane === "iam") return "operator"
  if (caller.lane === "cli-session") return "cli"
  if (caller.lane === "newsroom-session") return "newsroom"
  return "signed-in"
}

export function editOriginOfIdentity(identity: unknown, clients: CurationClients = curationClientsFromEnvironment()): EditOrigin {
  return editOriginOf(classifyCurationCaller(identity, clients))
}
