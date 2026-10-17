import { z } from "zod";
import { APPROVED_PRIMING_PROOF_REPORTS } from "./approved-priming-proof-reports";

export const PRIMING_PROOF_REPORT_VERSION = "cyclotron-priming-proof/v1";

const nullableRatio = z.number().min(0).max(1).nullable();

const primingProofPointSchema = z.object({
  labels: z.number().int().min(0),
  labelsByClass: z.record(z.string(), z.number().int().min(0)),
  decided: z.number().int().min(0),
  agreement: nullableRatio,
  precision: nullableRatio,
  recall: nullableRatio,
  confusion: z.object({
    truePositives: z.number().int().min(0),
    falsePositives: z.number().int().min(0),
    trueNegatives: z.number().int().min(0),
    falseNegatives: z.number().int().min(0),
  }),
});

export const primingProofReportSchema = z.object({
  version: z.literal(PRIMING_PROOF_REPORT_VERSION),
  proofId: z.string().min(1),
  publication: z.string().min(1),
  cyclotronId: z.string().min(1),
  question: z.string().min(1),
  labels: z.array(z.string().min(1)).length(2),
  positiveLabel: z.string().min(1),
  decisionModel: z.string().nullable(),
  ranAt: z.string().min(1),
  heldOut: z.object({
    size: z.number().int().min(1),
    byLabel: z.record(z.string(), z.number().int().min(0)),
    fingerprint: z.string().min(1),
    frozenAt: z.string().min(1),
    source: z.string().min(1),
  }),
  priming: z.object({
    acceptedExamples: z.number().int().min(0),
    excludedBecauseInHeldOut: z.number().int().min(0),
    fingerprint: z.string().nullable(),
    source: z.string().min(1),
    order: z.string().min(1),
  }),
  conditions: z.object({
    freshStorePerPoint: z.boolean(),
    rubric: z.string().min(1),
    optimizer: z.boolean(),
    reviewProgram: z.boolean(),
  }),
  points: z.array(primingProofPointSchema).min(1),
});

export type PrimingProofReport = z.infer<typeof primingProofReportSchema>;
export type PrimingProofPoint = z.infer<typeof primingProofPointSchema>;

export type PrimingProofHeadline = {
  baseline: PrimingProofPoint;
  latest: PrimingProofPoint;
  agreementChangeInPoints: number | null;
};

export function parsePrimingProofReport(value: unknown): PrimingProofReport {
  const report = primingProofReportSchema.parse(value);
  if (report.points[0].labels !== 0) {
    throw new Error("A priming proof report must start with the zero-label baseline.");
  }
  return report;
}

export function approvedPrimingProofReport(brandId: string): PrimingProofReport | null {
  const approvedReport = APPROVED_PRIMING_PROOF_REPORTS[brandId];
  return approvedReport === undefined ? null : parsePrimingProofReport(approvedReport);
}

export function primingProofHeadline(report: PrimingProofReport): PrimingProofHeadline {
  const baseline = report.points[0];
  const latest = report.points[report.points.length - 1];
  const agreementChangeInPoints =
    baseline.agreement === null || latest.agreement === null
      ? null
      : Math.round((latest.agreement - baseline.agreement) * 1000) / 10;
  return { baseline, latest, agreementChangeInPoints };
}

export function formatProofPercentage(ratio: number | null): string {
  return ratio === null ? "n/a" : `${Math.round(ratio * 1000) / 10}%`;
}
