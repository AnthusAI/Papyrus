import { notFound, redirect } from "next/navigation";
import { EditionRoutePage } from "../../edition-route-page";
import { parseEditionPageRoute } from "../../../../../../lib/edition-routes";
import { editionsEnabled, getDefaultPretextLayout, getForcedPresentation } from "../../../../../../lib/site-brand";
import { generateEditionPageStaticParams } from "../../../../../../lib/reader-static-params";
// Keep in sync with READER_REVALIDATE_SECONDS in lib/reader-route-config.ts
export const revalidate = 60;

export async function generateStaticParams() {
  return generateEditionPageStaticParams();
}

type EditionPageRouteProps = {
  params: Promise<{
    year: string;
    month: string;
    day: string;
    pageNumber: string;
  }>;
};

export default async function EditionPageRoute({ params }: EditionPageRouteProps) {
  if (!editionsEnabled()) notFound();
  const { year, month, day, pageNumber } = await params;
  const route = parseEditionPageRoute({ year, month, day, pageNumber });
  if (!route) notFound();
  if (!route.isCanonical) redirect(route.canonicalPath);

  return (
    <EditionRoutePage
      day={day}
      initialPageNumber={route.pageNumber}
      lockedPresentation={getForcedPresentation() ?? getDefaultPretextLayout()}
      month={month}
      year={year}
    />
  );
}
