"use client";

import { useState } from "react";
import { PrimingPanel, type PrimingPanelProps } from "cyclotron/components/priming-panel";
import { Button } from "./ui/button";

/** Papyrus supplies its transport/configuration; Cyclotron owns preview and labels. */
export function ReferencePriming(props: PrimingPanelProps) {
  const [open, setOpen] = useState(false);
  return (
    <section className="shrink-0 space-y-3" aria-label="Representative reference examples">
      <Button aria-expanded={open} onClick={() => setOpen((value) => !value)} variant="outline">
        {open ? "Hide example priming" : "Curate reference examples (optional)"}
      </Button>
      {open ? <div className="max-h-[55dvh] space-y-3 overflow-y-auto pr-1"><p className="text-sm text-muted-foreground">Corrections to extracted content: describe what needs fixing, then enter the corrected title and abstract or summary. The note is saved with your correction; it does not automatically regenerate the content. Choose Publish / Not publish separately. An explanation of that judgment is optional.</p><PrimingPanel {...props} renderItem={props.renderItem ?? ((item) => <div className="space-y-2"><p className="whitespace-pre-wrap text-sm">{String(item.values.abstract ?? item.values.text ?? "")}</p><p className="break-all text-xs text-muted-foreground">{String(item.values.source_uri ?? "")}</p></div>)} /></div> : null}
    </section>
  );
}
