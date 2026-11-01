"use client";

import { useMemo, type ReactNode } from "react";
import { localPreviewReferenceLinkItems, localPreviewReferenceLinks } from "../lib/local-preview-reference-links";
import { ReferenceLinksStoreProvider, createMemoryReferenceLinksStore } from "./reference-links-context";
import { createNetworkReferenceLinksStore } from "./reference-links-client";

/** Gives the newsroom its related links: read and written through the backend, or kept in memory with sample links in the demo. */
export function ReferenceLinksProvider({ demo, children }: { demo: boolean; children: ReactNode }) {
  const store = useMemo(() => (demo
    ? createMemoryReferenceLinksStore({ items: localPreviewReferenceLinkItems(), links: localPreviewReferenceLinks() })
    : createNetworkReferenceLinksStore()), [demo]);
  return <ReferenceLinksStoreProvider store={store}>{children}</ReferenceLinksStoreProvider>;
}
