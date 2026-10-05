import { NewsDeskPage } from "../../components/news-desk-page";

export const dynamic = "force-dynamic";

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
