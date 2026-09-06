import { notFound, redirect } from "next/navigation";
import { pretextRenderer, type PresentationTarget } from "../../../../renderers/pretext";
import { loadCachedEditionContent } from "../../../../lib/cached-content-repository";
import { parseEditionDateRoute } from "../../../../lib/edition-routes";
import type { EditionPresentationFormat } from "../../../../lib/content-types";

type EditionRoutePageProps = {
  year: string;
  month: string;
  day: string;
  initialPageNumber?: number;
  lockedPresentation?: EditionPresentationFormat;
  target?: PresentationTarget;
};

export async function EditionRoutePage({
  year,
  month,
  day,
  initialPageNumber = 1,
  lockedPresentation,
  target = { kind: "edition" },
}: EditionRoutePageProps) {
  const route = parseEditionDateRoute({ year, month, day });
  if (!route) notFound();
  if (!route.isCanonical) redirect(route.canonicalPath);

  try {
    const content = await loadCachedEditionContent({
      editionDate: route.editionDate,
    });
    if (initialPageNumber < 1 || initialPageNumber > content.layoutPlan.pages.length) notFound();
    if (target.kind === "section" && !content.sections.some((section) => section.key === target.sectionKey)) notFound();
    return (
      <pretextRenderer.renderEdition
        content={content}
        editionBasePath={route.canonicalPath}
        initialPageNumber={initialPageNumber}
        lockedPresentation={lockedPresentation}
        target={target}
      />
    );
  } catch (error) {
    if (isMissingGraphQLEditionError(error)) notFound();
    throw error;
  }
}

function isMissingGraphQLEditionError(error: unknown): boolean {
  return error instanceof Error && error.message.includes("No published GraphQL edition found");
}
