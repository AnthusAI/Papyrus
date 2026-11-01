import { REFERENCE_DATASOURCE, referenceDocument } from "../apl/reference";
import type { RenderDocumentDirective } from "../apl/support/directives";
import type { AplTheme } from "../apl/support/theme";
import type { ReviewDetails } from "./newsroom";

export type ReferenceCard = Pick<ReviewDetails, "title" | "deck" | "summary" | "siteName" | "sourcePublishedAt"> & {
  position: number;
  total: number;
  queueName: string;
};

function dateline(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const time = Date.parse(value);
  return Number.isNaN(time) ? undefined : new Date(time).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
}

/** The RenderDocument directive for the Reference under review. The card shows the whole summary; speech reads a part of it. */
export function referenceDirective(card: ReferenceCard, theme: AplTheme): RenderDocumentDirective {
  const queueLabel = `${card.queueName.charAt(0).toUpperCase()}${card.queueName.slice(1)} · ${card.position} of ${card.total}`;
  const meta = [card.siteName, dateline(card.sourcePublishedAt)].filter((part): part is string => Boolean(part)).join(" · ");
  return {
    type: "Alexa.Presentation.APL.RenderDocument",
    token: referenceDocument.id,
    document: referenceDocument.document,
    datasources: {
      [REFERENCE_DATASOURCE]: {
        queueLabel,
        title: card.title,
        meta,
        ...(card.deck ? { deck: card.deck } : {}),
        ...(card.summary && card.summary !== card.deck ? { summary: card.summary } : {}),
        theme,
      },
    },
  };
}
