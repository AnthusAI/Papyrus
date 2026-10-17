import { NextResponse } from "next/server";
import { approvedPrimingProofReport } from "../../../../lib/priming-proof-report";
import { SITE_BRAND } from "../../../../lib/site-brand";

export function GET() {
  const report = approvedPrimingProofReport(SITE_BRAND.id);
  if (report === null) {
    return NextResponse.json({ error: "No approved priming proof report for this publication yet." }, { status: 404 });
  }
  return NextResponse.json(report);
}
