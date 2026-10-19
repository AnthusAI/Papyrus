import {
  formatProofPercentage,
  primingProofHeadline,
  type PrimingProofReport,
} from "../lib/priming-proof-report";

function ProofMethod({ heldOutSize, teachingSource, design }: { heldOutSize: number | null; teachingSource: string | null; design: string | null }) {
  return (
    <section aria-labelledby="priming-proof-method" className="space-y-2 text-sm leading-relaxed">
      <h2 id="priming-proof-method" className="text-base font-semibold uppercase tracking-wide">How the number is made</h2>
      {design === null ? (
        <p>
          Editors already decided which candidate sources belong in this publication. A fixed, balanced sample of those
          decisions{heldOutSize === null ? "" : ` (${heldOutSize} sources)`} is frozen as the held-out set and never used
          for teaching. A classifier that always gives the same answer agrees on half of it.
        </p>
      ) : (
        <p>
          Editors already decided which candidate sources belong in this publication
          {heldOutSize === null ? "" : `, ${heldOutSize} of them`}. Design: {design}. No source is ever judged by a
          classifier that was taught from that same source. The two outcomes are not equally common, so read agreement
          beside precision and recall: a classifier that always gives the majority answer would still agree often.
        </p>
      )}
      <p>
        Editors teach the classifier with labels: their other reviews of candidate sources, and sources they paste,
        check after Papyrus extracts them, and mark publish or reject.
        {teachingSource === null ? "" : ` This run taught from ${teachingSource}.`} Each point below starts a fresh
        classifier that sees only the first N of those labels, then decides
        every held-out source once. Nothing else changes between points: the same decision model, the publication&apos;s
        mission and policies as the only rubric, and no automatic rubric rewriting.
      </p>
    </section>
  );
}

export function PrimingProofPage({ report }: { report: PrimingProofReport | null }) {
  if (report === null) {
    return (
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-10" data-priming-proof="pending">
        <header className="space-y-2 border-b pb-4">
          <h1 className="text-3xl font-bold">Does teaching the classifier work?</h1>
          <p className="text-muted-foreground">No approved proof run has been published for this publication yet.</p>
        </header>
        <ProofMethod heldOutSize={null} teachingSource={null} design={null} />
      </main>
    );
  }
  const { baseline, latest, agreementChangeInPoints } = primingProofHeadline(report);
  const [positiveLabel, negativeLabel] = [report.positiveLabel, report.labels.find((label) => label !== report.positiveLabel)];
  return (
    <main className="mx-auto max-w-3xl space-y-8 px-4 py-10" data-priming-proof="published">
      <header className="space-y-3 border-b pb-4">
        <h1 className="text-3xl font-bold">Does teaching the classifier work?</h1>
        <p className="text-lg" data-priming-proof-headline>
          Agreement with editors went from <strong>{formatProofPercentage(baseline.agreement)}</strong> with no labels to{" "}
          <strong>{formatProofPercentage(latest.agreement)}</strong> after {latest.labels} labels
          {agreementChangeInPoints === null ? "" : ` (${agreementChangeInPoints >= 0 ? "+" : ""}${agreementChangeInPoints} points)`}.
        </p>
        <p className="text-sm text-muted-foreground">
          {report.publication} · question: “{report.question}” · held-out set of {report.heldOut.size} sources frozen{" "}
          {report.heldOut.frozenAt.slice(0, 10)} · run {report.ranAt.slice(0, 10)}
          {report.decisionModel ? ` · decision model ${report.decisionModel}` : ""}
        </p>
      </header>
      <section aria-labelledby="priming-proof-points" className="space-y-2">
        <h2 id="priming-proof-points" className="text-base font-semibold uppercase tracking-wide">Before and after</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm tabular-nums">
            <thead>
              <tr className="border-b">
                <th scope="col" className="py-2 pr-4">Editor labels</th>
                <th scope="col" className="py-2 pr-4">Agreement</th>
                <th scope="col" className="py-2 pr-4">Precision ({positiveLabel})</th>
                <th scope="col" className="py-2 pr-4">Recall ({positiveLabel})</th>
                <th scope="col" className="py-2">Labels used</th>
              </tr>
            </thead>
            <tbody>
              {report.points.map((point) => (
                <tr key={point.labels} className="border-b" data-priming-proof-point={point.labels}>
                  <td className="py-2 pr-4">{point.labels}</td>
                  <td className="py-2 pr-4">{formatProofPercentage(point.agreement)}</td>
                  <td className="py-2 pr-4">{formatProofPercentage(point.precision)}</td>
                  <td className="py-2 pr-4">{formatProofPercentage(point.recall)}</td>
                  <td className="py-2">
                    {point.labelsByClass[positiveLabel] ?? 0} {positiveLabel}
                    {negativeLabel ? `, ${point.labelsByClass[negativeLabel] ?? 0} ${negativeLabel}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <ProofMethod heldOutSize={report.heldOut.size} teachingSource={report.priming.source} design={report.heldOut.design ?? null} />
      <p className="break-all text-xs text-muted-foreground">
        Held-out fingerprint {report.heldOut.fingerprint}
        {report.priming.fingerprint ? ` · labels fingerprint ${report.priming.fingerprint}` : ""}
      </p>
    </main>
  );
}
