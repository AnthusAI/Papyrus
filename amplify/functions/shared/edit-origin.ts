import { classifyCurationCaller, cliClientIdFromEnvironment, type CurationCaller } from "./curation-caller"

/**
 * Where an editor's decision was made, written on the record it changes so a later reader can tell them apart.
 *
 * A person may make these decisions from the CLI as well as in the Newsroom (concept names, descriptions, links between concepts), so the CLI is not
 * refused. But a record of "an editor accepted this" must not read as if the editor did it in the Newsroom when it was done through the CLI, where a
 * script or an agent may be working in the editor's own session. The origin comes from the token's app client (`curation-caller.ts`), never from
 * anything the caller sends:
 *
 * - `cli`: a session on the CLI client.
 * - `newsroom`: a session on any other client.
 * - `signed-in`: a person's session on a site that has not named a CLI client, so the two cannot be told apart.
 * - `operator`: AWS credentials, no person signed in.
 * - `signed-in` also covers a session whose client cannot be read.
 *
 * The origin is a plain note, never a gate: a signed-in editor or admin decides as themselves from the CLI or the Newsroom, and an agent working
 * through their session acts for them.
 */
export type EditOrigin = "cli" | "newsroom" | "signed-in" | "operator"

export function editOriginOf(caller: CurationCaller): EditOrigin {
  // A session whose sign-in client cannot be read is still a signed-in person; `via` is a note, never a gate.
  if (caller.lane === "unreadable-client-session") return "signed-in"
  if (caller.lane === "iam") return "operator"
  if (caller.lane === "cli-session") return "cli"
  if (caller.lane === "newsroom-session") return "newsroom"
  return "signed-in"
}

export function editOriginOfIdentity(identity: unknown, cliClientId: string | null = cliClientIdFromEnvironment()): EditOrigin {
  return editOriginOf(classifyCurationCaller(identity, cliClientId))
}
