import { EditionRoutePage } from "./edition-route-page";
import { generateEditionDateStaticParams } from "../../../../lib/reader-static-params";

// Keep in sync with READER_REVALIDATE_SECONDS in lib/reader-route-config.ts
export const revalidate = 60;

export async function generateStaticParams() {
  return generateEditionDateStaticParams();
}

type DateEditionPageProps = {
  params: Promise<{
    year: string;
    month: string;
    day: string;
  }>;
};

export default async function DateEditionPage({ params }: DateEditionPageProps) {
  const { year, month, day } = await params;
  return <EditionRoutePage day={day} month={month} year={year} />;
}
