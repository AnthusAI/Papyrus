import { notFound, redirect } from "next/navigation";
import { EditionRoutePage } from "../../edition-route-page";
import { createSectionKey } from "../../../../../../lib/edition-sections";
import { parseEditionSectionRoute } from "../../../../../../lib/edition-routes";
// Keep in sync with READER_REVALIDATE_SECONDS in lib/reader-route-config.ts
export const revalidate = 60;

type EditionSectionRouteProps = {
  params: Promise<{
    year: string;
    month: string;
    day: string;
    sectionKey: string;
  }>;
};

export default async function EditionSectionRoute({ params }: EditionSectionRouteProps) {
  const { year, month, day, sectionKey } = await params;
  const normalizedSectionKey = createSectionKey(sectionKey);
  const route = parseEditionSectionRoute({ year, month, day, sectionKey: normalizedSectionKey });
  if (!route) notFound();
  if (!route.isCanonical) redirect(route.canonicalPath);

  return (
    <EditionRoutePage
      day={day}
      month={month}
      target={{ kind: "section", sectionKey: route.sectionKey }}
      year={year}
    />
  );
}
