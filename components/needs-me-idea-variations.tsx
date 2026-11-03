"use client";

import { Columns2Icon } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { StoryVariationsPanel } from "./story-variations";
import { resolveVariationSource } from "./story-variations-client";
import { saveVariationAsNextVersion } from "./story-variations-accept";

/** The variations of one idea of a Needs me batch: nothing when it has none, otherwise a button that opens them side by side right under the idea. */
export function BatchIdeaVariations({ lineageId, demo, decidedBy }: { lineageId: string; demo: boolean; decidedBy: string }) {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    resolveVariationSource(demo).load(lineageId).then((rows) => { if (live) setCount(rows.length); }, () => undefined);
    return () => { live = false; };
  }, [demo, lineageId]);
  if (!count) return null;
  return (
    <div className="space-y-2 pt-1.5" data-idea-variations={lineageId}>
      <button
        aria-expanded={open}
        className={cn("inline-flex min-h-10 max-w-full items-center gap-1.5 rounded-full bg-[var(--feed-control)] px-3 text-xs font-medium text-foreground outline-none transition-colors hover:bg-[var(--feed-control)]/70 focus-visible:ring-2 focus-visible:ring-ring")}
        data-idea-variations-toggle
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <Columns2Icon aria-hidden="true" className="size-3.5" />{open ? "Hide the variations" : `${count} ${count === 1 ? "variation" : "variations"}`}
      </button>
      {open ? (
        <StoryVariationsPanel
          applyWording={async (variation) => { await saveVariationAsNextVersion(lineageId, variation, demo); }}
          decidedBy={decidedBy}
          demo={demo}
          lineageId={lineageId}
        />
      ) : null}
    </div>
  );
}
