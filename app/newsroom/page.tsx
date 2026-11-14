import type { Metadata } from "next";
import { NewsDeskPage } from "../../components/news-desk-page";
import { getSiteBrand } from "../../lib/site-brand";

export const dynamic = "force-dynamic";

/** The browser title of the newsroom home, which is the page the wordmark opens. */
export function generateMetadata(): Metadata {
  return { title: `Newsroom home · ${getSiteBrand().appTitle}` };
}

export type NewsDeskRootSearchParams = {
  demo?: string | string[];
  section?: string | string[];
  tab?: string | string[];
  panel?: string | string[];
  reference?: string | string[];
  category?: string | string[];
  node?: string | string[];
  assignment?: string | string[];
  message?: string | string[];
  user?: string | string[];
  item?: string | string[];
  q?: string | string[];
  anchorKind?: string | string[];
  anchorId?: string | string[];
  anchorLineageId?: string | string[];
  maxTokens?: string | string[];
  from?: string | string[];
};

type NewsDeskRootPageProps = {
  searchParams?: Promise<NewsDeskRootSearchParams>;
};

export default function NewsDeskRootPage({ searchParams }: NewsDeskRootPageProps) {
  return <NewsDeskPage searchParams={searchParams} />;
}
