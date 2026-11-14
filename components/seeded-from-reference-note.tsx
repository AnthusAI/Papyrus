"use client";

import { InfoIcon } from "lucide-react";
import { readSeededFrom } from "../lib/story-from-reference";

/**
 * A plain note at the top of a Story that Create Story started from a Reference: what is in the draft, whose it is, and that the image needs a rights check
 * before publishing. It shows while the story's front matter carries `seededFrom`, and says nothing about stories written any other way.
 */
export function SeededFromReferenceNote({ frontMatterYaml }: { frontMatterYaml: string | null | undefined }) {
  const seeded = readSeededFrom(frontMatterYaml);
  if (!seeded) return null;
  const draft = seeded.summary === "included"
    ? "The text is a starting draft: the Reference's generated summary, with the source link and attribution below it. Rewrite it in your own words."
    : seeded.summary === "withheld"
      ? "The Reference's summary repeated the source's own words, so it was left out. Only the source link and attribution are here: write the Story in your own words."
      : "The Reference had no summary, so only the source link and attribution are here. Write the Story in your own words.";
  return (
    <aside aria-label="Started from a Reference" className="flex gap-x-2 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)]/60 p-3 text-sm leading-relaxed" data-seeded-from-reference role="note">
      <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <div className="space-y-1">
        <p><strong className="font-semibold">Started from a Reference.</strong> {draft}</p>
        {seeded.imageUrl ? (
          <p data-seeded-image-note>
            The image is {seeded.imageCredit ? <>credited as <q>{seeded.imageCredit}</q> and </> : null}taken from another site, not ours. Check that you have the right to publish it, or replace it, before this Story goes out.
          </p>
        ) : null}
      </div>
    </aside>
  );
}
