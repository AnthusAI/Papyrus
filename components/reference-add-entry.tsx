"use client";

import { useState } from "react";
import type { PrimingPanelProps } from "cyclotron/components/priming-panel";
import { ReferenceCyclotronPriming, type PrimingFormInput } from "./reference-cyclotron-priming";
import { ReferencePriming } from "./reference-priming";
import type { PrimingRequestView } from "../lib/relevance-status";
import { Button } from "./ui/button";

export type ReferenceUrlOption = {
  labels: readonly string[];
  requests: PrimingRequestView[];
  onRequest: (input: PrimingFormInput) => Promise<void> | void;
};

type Option = "url" | "file";

/**
 * The one place an editor adds a reference. "Paste a URL" is always offered when
 * the host can take one. "Import a file" appears only when a curation session
 * (or the host) supplies the import transport, so without one it never renders.
 */
export function ReferenceAddEntry({
  url,
  importOptions,
}: {
  url?: ReferenceUrlOption | null;
  importOptions?: PrimingPanelProps | null;
}) {
  const [chosen, setChosen] = useState<Option>("url");
  const [fileOpened, setFileOpened] = useState(false);
  const [saved, setSaved] = useState("");
  if (!url && !importOptions) return null;

  const option: Option = importOptions && (!url || chosen === "file") ? "file" : "url";
  const choose = (next: Option) => {
    setChosen(next);
    if (next === "file") setFileOpened(true);
  };

  return (
    <section aria-label="Add a reference" className="shrink-0 space-y-3" data-add-reference>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Add a reference</h3>
        {url && importOptions ? (
          <div aria-label="How to add a reference" className="flex gap-2" role="group">
            <Button aria-pressed={option === "url"} onClick={() => choose("url")} size="sm" type="button" variant={option === "url" ? "secondary" : "outline"}>Paste a URL</Button>
            <Button aria-pressed={option === "file"} onClick={() => choose("file")} size="sm" type="button" variant={option === "file" ? "secondary" : "outline"}>Import a file</Button>
          </div>
        ) : null}
      </div>
      {url ? (
        <div hidden={option !== "url"}>
          <ReferenceCyclotronPriming labels={url.labels} onRequestPriming={url.onRequest} requests={url.requests} />
        </div>
      ) : null}
      {importOptions && (fileOpened || !url) ? (
        <div className="max-h-[55dvh] space-y-3 overflow-y-auto pr-1" hidden={option !== "file"}>
          <ReferencePriming
            {...importOptions}
            onAccepted={(draft) => {
              setSaved(`Added ${draft.rows.length} reference${draft.rows.length === 1 ? "" : "s"}.`);
              importOptions.onAccepted?.(draft);
            }}
          />
          {saved ? <p role="status">{saved}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
