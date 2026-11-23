/**
 * The console's door to the poke-in operations (PPY-e6f31e; src/papyrus_content/agent_poke_in.py), the same rows of the operation table `papyrus agents pause|resume|pauses|wake`
 * runs. Pausing, resuming and reading the pauses go to the site's agent-policy function (`agentPolicyChange`), which admits only an admin signed in to the console
 * and catches up the wakes a pause stopped when it resumes. Wake now goes to the Automation page's function (`agentWake`), which admits editors and admins. The
 * browser sends the operation and its input; who is asking comes from the signed-in session.
 */
import { AGENT_POLICY_CHANGE } from "./announcement-review-client";

export const AGENT_WAKE = "mutation AgentWake($input: AWSJSON!) { agentWake(input: $input) }";

export type PauseShown = { paused: false } | { paused: true; reason: string; pausedAt?: string | null; pausedBy?: string | null };
export type Pauses = { policyVersion: number; site: PauseShown; agents: Record<string, PauseShown> };
export type PauseResult = { scope: "agent" | "site"; agent: string | null; paused: boolean; changed: boolean; policyVersion: { before: number; after: number } };
export type ResumeResult = PauseResult & { caughtUp: { agent: string; subject: string; wakeKey: string; repeats: string }[]; notes: string[] };
export type WakeResult = { agent: string; subject: string; wakeKey: string; repeats: string; requestedBy: string; reason: string };

export type AgentPokeInApi = {
  pauses(): Promise<Pauses>;
  pause(agent: string | null, reason: string): Promise<PauseResult>;
  resume(agent: string | null, reason: string): Promise<ResumeResult>;
  wake(agent: string, subject: string, reason: string): Promise<WakeResult>;
};

/** What the page sends a GraphQL request through: Amplify's `client.graphql`, or a fake in tests. */
export type PokeInTransport = (request: { query: string; variables: { input: string } }) => Promise<unknown>;

type GraphQLResult = { data?: Record<string, unknown>; errors?: { message?: string; errorType?: string }[] };

/** A refusal in words a person reads; the function's own sentence when it gave one. */
export function pokeInRefusalText(code: string, message?: string): string {
  if (message) return message;
  if (code === "human_required") return "Only a person signed in to the newsroom does this. Nothing was changed.";
  if (code === "not_authorized" || code === "forbidden") return "Pausing and resuming agents is for admins. Nothing was changed.";
  return "The agents could not be reached. Nothing was changed; try again in a minute.";
}

/** The status of the site or of one agent, in words with a mark: never colour alone. */
export function pauseText(shown: PauseShown | undefined, name: string): { mark: string; words: string } {
  if (!shown || !shown.paused) return { mark: "▶", words: `${name} is running.` };
  const by = shown.pausedBy ? ` by ${shown.pausedBy}` : "";
  const at = shown.pausedAt ? ` since ${shown.pausedAt.replace("T", " ").replace(/:\d\dZ$/, " UTC")}` : "";
  return { mark: "⏸", words: `${name} is paused${by}${at}: ${shown.reason}` };
}

/** What a resume did, in words: how many stopped wakes went out again, and anything it could not catch up. */
export function resumeText(result: ResumeResult, name: string): string {
  const count = result.caughtUp.length;
  const sent = count === 0 ? "No stopped wake needed sending again." : `${count} stopped ${count === 1 ? "wake was" : "wakes were"} sent again, one for each subject.`;
  return [`${name} resumed.`, sent, ...result.notes].join(" ");
}

export function wakeText(result: WakeResult): string {
  return `${result.agent} was woken for ${result.subject}. It runs once, as soon as the site's queue reaches it.`;
}

export function agentPokeInApi(transport: PokeInTransport): AgentPokeInApi {
  const send = async <T>(query: string, field: string, request: Record<string, unknown>): Promise<T> => {
    let result: GraphQLResult;
    try {
      result = (await transport({ query, variables: { input: JSON.stringify(request) } })) as GraphQLResult;
    } catch (error) {
      result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
    }
    if (result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`))) throw new Error(pokeInRefusalText("forbidden"));
    const raw = result.data?.[field];
    if (result.errors?.length || raw === undefined || raw === null) throw new Error(pokeInRefusalText("unavailable"));
    const answer = (typeof raw === "string" ? JSON.parse(raw) : raw) as { ok?: boolean; result?: T; error?: string; message?: string };
    if (!answer || answer.ok !== true || answer.result === undefined) throw new Error(pokeInRefusalText(String(answer?.error ?? "unavailable"), answer?.message));
    return answer.result;
  };
  const policy = <T>(request: Record<string, unknown>) => send<T>(AGENT_POLICY_CHANGE, "agentPolicyChange", request);
  return {
    pauses: () => policy<Pauses>({ op: "agents_pauses" }),
    pause: (agent, reason) => policy<PauseResult>({ op: "agents_pause", ...(agent ? { agent } : {}), reason: reason.trim() }),
    resume: (agent, reason) => policy<ResumeResult>({ op: "agents_resume", ...(agent ? { agent } : {}), reason: reason.trim() }),
    wake: (agent, subject, reason) => send<WakeResult>(AGENT_WAKE, "agentWake", { op: "agents_wake", agent, subject: subject.trim(), reason: reason.trim() }),
  };
}

/** The demo workspace (`?demo=1`): the same answers, in memory. Nothing is sent anywhere. */
export function createDemoPokeInApi(): AgentPokeInApi {
  let version = 1;
  const state: Pauses = { policyVersion: version, site: { paused: false }, agents: { announce: { paused: false }, rate: { paused: false } } };
  const now = () => new Date().toISOString().replace(/\.\d+Z$/, "Z");
  return {
    pauses: async () => JSON.parse(JSON.stringify({ ...state, policyVersion: version })),
    pause: async (agent, reason) => {
      const before = version;
      const shown: PauseShown = { paused: true, reason: reason.trim(), pausedAt: now(), pausedBy: "you (demo)" };
      if (agent) state.agents[agent] = shown; else state.site = shown;
      version += 1;
      return { scope: agent ? "agent" : "site", agent, paused: true, changed: true, policyVersion: { before, after: version } };
    },
    resume: async (agent) => {
      const before = version;
      if (agent) state.agents[agent] = { paused: false }; else state.site = { paused: false };
      version += 1;
      return { scope: agent ? "agent" : "site", agent, paused: false, changed: true, policyVersion: { before, after: version }, caughtUp: [], notes: [] };
    },
    wake: async (agent, subject, reason) => ({ agent, subject, wakeKey: `${agent}|${subject}|demo|woken`, repeats: `${agent}|${subject}|demo`, requestedBy: "you (demo)", reason }),
  };
}
