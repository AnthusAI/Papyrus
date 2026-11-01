import { parseDocument } from "yaml";

export const GENERATED_FRONT_MATTER_KEY = "generated";
export const GENERATED_DECISION_KEY = "decision";

export type IdeaDecisionChoice = "accept" | "reject";

export type IdeaDecisionRecord = {
  decision: IdeaDecisionChoice;
  reasonCode: string | null;
  note: string;
  decidedBy: string;
  decidedAt: string;
};

export function isGeneratedIdeaFrontMatter(frontMatterYaml: string | null | undefined): boolean {
  if (!frontMatterYaml?.trim()) return false;
  const document = parseDocument(frontMatterYaml);
  if (document.errors.length) return false;
  return document.has(GENERATED_FRONT_MATTER_KEY);
}

export function readIdeaDecision(frontMatterYaml: string | null | undefined): IdeaDecisionRecord | null {
  if (!frontMatterYaml?.trim()) return null;
  const document = parseDocument(frontMatterYaml);
  if (document.errors.length) return null;
  const generated = document.get(GENERATED_FRONT_MATTER_KEY) as { toJSON?: () => unknown } | null;
  const value = generated?.toJSON?.() as Record<string, unknown> | undefined;
  const decision = value?.[GENERATED_DECISION_KEY] as Record<string, unknown> | undefined;
  if (!decision || (decision.decision !== "accept" && decision.decision !== "reject")) return null;
  return {
    decision: decision.decision,
    reasonCode: typeof decision.reasonCode === "string" ? decision.reasonCode : null,
    note: typeof decision.note === "string" ? decision.note : "",
    decidedBy: typeof decision.decidedBy === "string" ? decision.decidedBy : "",
    decidedAt: typeof decision.decidedAt === "string" ? decision.decidedAt : "",
  };
}

/** Records the editor's decision on a generated idea at `generated.decision`, keeping every other line and comment as written. */
export function writeIdeaDecision(frontMatterYaml: string, record: IdeaDecisionRecord): string {
  const document = parseDocument(frontMatterYaml);
  if (document.errors.length || !document.has(GENERATED_FRONT_MATTER_KEY)) return frontMatterYaml;
  document.setIn([GENERATED_FRONT_MATTER_KEY, GENERATED_DECISION_KEY], document.createNode({
    decision: record.decision,
    reasonCode: record.reasonCode,
    note: record.note,
    decidedBy: record.decidedBy,
    decidedAt: record.decidedAt,
  }));
  return document.toString();
}
