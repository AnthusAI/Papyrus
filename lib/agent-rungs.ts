/**
 * The console's door to the rung board (src/papyrus_content/agent_policy/console_rungs.py): every agent's rung on the site, and setting one, with a person's
 * ordinary admin sign-in. Both go to the site's agent-policy function (`agentPolicyChange`), which admits only an admin signed in to the console and runs the
 * same checks as `papyrus agents set-rung`: the rung is one the agent's definition uses, never above it, never publish_auto, and a reason is kept.
 */
import { AGENT_POLICY_CHANGE } from "./announcement-review-client";

export type RungAgent = { id: string; responsibility: string; rung: string; ceiling: string; choices: string[]; overrides: number };
export type RungBoard = { policyVersion: number; agents: RungAgent[] };
export type RungChange = {
  id: string;
  responsibility: string;
  rung: string;
  ceiling: string;
  reason: string;
  changed: boolean;
  applied: boolean;
  before: { policyVersion: number; entry: { rung?: string } | null };
  after: { policyVersion: number; entry: { rung?: string } | null };
  board: RungBoard;
};

export type AgentRungsApi = {
  board(): Promise<RungBoard>;
  setRung(agent: string, rung: string, reason: string): Promise<RungChange>;
};

export type RungsTransport = (request: { query: string; variables: { input: string } }) => Promise<unknown>;

type GraphQLResult = { data?: Record<string, unknown>; errors?: { message?: string; errorType?: string }[] };

/** Each rung's name in the console, in plain words; the stored value (off, observe, propose, ...) stays the policy's and the command line's. */
export const RUNG_LABELS: Record<string, string> = {
  off: "Off",
  observe: "Watch only",
  propose: "Suggest",
  draft: "Write drafts",
  prepare: "Prepare for approval",
  publish_soft: "Publish, with undo",
  publish_auto: "Publish on its own",
};

/** What each rung lets an agent do, in a person's words. */
export const RUNG_WORDS: Record<string, string> = {
  off: "does not run",
  observe: "runs and records what it would do; changes nothing",
  propose: "writes suggestions for a person to accept or ignore",
  draft: "saves drafts a person reviews",
  prepare: "gets work ready for a person to approve",
  publish_soft: "publishes, and a person can undo it",
  publish_auto: "publishes with no person involved",
};

export function rungLabel(rung: string): string {
  return RUNG_LABELS[rung] ?? rung;
}

export function rungText(rung: string): string {
  return RUNG_WORDS[rung] ? `${rungLabel(rung)}: ${RUNG_WORDS[rung]}` : rungLabel(rung);
}

/** A refusal in words a person reads; the function's own sentence when it gave one. */
export function rungRefusalText(code: string, message?: string): string {
  if (message) return message;
  if (code === "human_required") return "Only a person signed in to the newsroom sets a rung. Nothing was changed.";
  if (code === "not_authorized" || code === "forbidden") return "Setting an agent's rung is for admins. Nothing was changed.";
  return "The agent policy could not be reached. Nothing was changed; try again in a minute.";
}

export function rungChangeText(change: RungChange): string {
  if (!change.changed) return `${change.responsibility} is already set to ${rungLabel(change.rung)}. Nothing was saved.`;
  const before = change.before.entry?.rung ?? "off";
  return `${change.responsibility} changed from ${rungLabel(before)} to ${rungLabel(change.rung)} (agent policy version ${change.after.policyVersion}). Its next run uses it.`;
}

export function agentRungsApi(transport: RungsTransport): AgentRungsApi {
  const send = async <T>(request: Record<string, unknown>): Promise<T> => {
    let result: GraphQLResult;
    try {
      result = (await transport({ query: AGENT_POLICY_CHANGE, variables: { input: JSON.stringify(request) } })) as GraphQLResult;
    } catch (error) {
      result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
    }
    if (result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`))) throw new Error(rungRefusalText("forbidden"));
    const raw = result.data?.agentPolicyChange;
    if (result.errors?.length || raw === undefined || raw === null) throw new Error(rungRefusalText("unavailable"));
    const answer = (typeof raw === "string" ? JSON.parse(raw) : raw) as { ok?: boolean; result?: T; error?: string; message?: string };
    if (!answer || answer.ok !== true || answer.result === undefined) throw new Error(rungRefusalText(String(answer?.error ?? "unavailable"), answer?.message));
    return answer.result;
  };
  return {
    board: () => send<RungBoard>({ op: "agents_rungs" }),
    setRung: (agent, rung, reason) => send<RungChange>({ op: "agents_set_rung", agent, rung, reason: reason.trim() }),
  };
}

/** The demo workspace (`?demo=1`): the same answers, in memory. Nothing is sent anywhere. */
export function createDemoRungsApi(): AgentRungsApi {
  const board: RungBoard = {
    policyVersion: 1,
    agents: [
      { id: "announce", responsibility: "announce", rung: "prepare", ceiling: "prepare", choices: ["off", "observe", "propose", "draft", "prepare"], overrides: 0 },
      { id: "rate", responsibility: "rate", rung: "observe", ceiling: "propose", choices: ["off", "observe", "propose"], overrides: 0 },
    ],
  };
  const copy = () => JSON.parse(JSON.stringify(board)) as RungBoard;
  return {
    board: async () => copy(),
    setRung: async (agent, rung, reason) => {
      const found = board.agents.find((item) => item.id === agent);
      if (!found) throw new Error(`${agent} is not an agent on this site.`);
      if (!found.choices.includes(rung)) throw new Error(`${agent} cannot be set to ${rung}. Set it to ${found.ceiling} or lower.`);
      if (!reason.trim()) throw new Error("A rung change needs a reason.");
      const before = { policyVersion: board.policyVersion, entry: { rung: found.rung } };
      const changed = found.rung !== rung;
      if (changed) {
        found.rung = rung;
        board.policyVersion += 1;
      }
      return { id: agent, responsibility: found.responsibility, rung, ceiling: found.ceiling, reason: reason.trim(), changed, applied: changed, before,
               after: { policyVersion: board.policyVersion, entry: { rung } }, board: copy() };
    },
  };
}
