"use client";

import { useState } from "react";
import { readIdeaDecision, type IdeaDecisionChoice, type IdeaDecisionRecord } from "../lib/idea-decision";
import { DecisionControl, type RatingFeedback } from "./decision-control";

/**
 * Accept or Reject on a generated idea, with an optional written reason, through the same control References use.
 * It records the decision and nothing else: the idea is not moved, approved or published by answering.
 */
export function IdeaDecision({
  decidedBy,
  disabledReason = null,
  frontMatterYaml,
  now = () => new Date().toISOString(),
  onDecide,
}: {
  decidedBy: string;
  disabledReason?: string | null;
  frontMatterYaml: string;
  now?: () => string;
  onDecide: (record: IdeaDecisionRecord) => Promise<void> | void;
}) {
  const saved = readIdeaDecision(frontMatterYaml);
  const [answer, setAnswer] = useState<IdeaDecisionChoice | null>(saved?.decision ?? null);
  const [note, setNote] = useState(saved?.note ?? "");
  const [feedback, setFeedback] = useState<RatingFeedback>({ phase: "idle" });

  const record = async (choice: IdeaDecisionChoice, text: string) => {
    setAnswer(choice);
    setFeedback({ phase: "saving" });
    try {
      await onDecide({ decision: choice, reasonCode: null, note: text.trim(), decidedBy, decidedAt: now() });
      setFeedback({ phase: "saved" });
    } catch (error) {
      setFeedback({ phase: "error", message: error instanceof Error ? error.message : "The decision could not be saved." });
    }
  };

  return (
    <section aria-label="Decide this idea" className="grid gap-y-2" data-idea-decision>
      <DecisionControl
        answer={answer}
        decided={feedback.phase === "saved" ? answer : saved?.decision ?? null}
        disabled={Boolean(disabledReason) || feedback.phase === "saving"}
        disabledReason={disabledReason}
        feedback={feedback}
        onChoose={(choice) => { if (choice !== answer || feedback.phase !== "saved") void record(choice, note); }}
        onReasonChange={setNote}
        onReasonCommit={() => { if (answer && feedback.phase === "saved") void record(answer, note); }}
        prediction={{ state: "none" }}
        reason={note}
        showPrediction={false}
      />
    </section>
  );
}
