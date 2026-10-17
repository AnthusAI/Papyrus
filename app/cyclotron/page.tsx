import type { Metadata } from "next";
import { PrimingProofPage } from "../../components/priming-proof-page";
import { approvedPrimingProofReport } from "../../lib/priming-proof-report";
import { SITE_BRAND } from "../../lib/site-brand";

export const metadata: Metadata = {
  title: `Cyclotron proof | ${SITE_BRAND.articleTitleSuffix}`,
  description: "How often the relevance classifier agrees with editors on a fixed held-out set, before and after editor labels.",
};

export default function CyclotronProof() {
  return <PrimingProofPage report={approvedPrimingProofReport(SITE_BRAND.id)} />;
}
