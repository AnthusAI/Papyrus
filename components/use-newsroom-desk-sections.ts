"use client";

import { useEffect, useState } from "react";
import type { NewsroomSectionRecord } from "../lib/category-repository";
import { loadEditorNewsroomSections } from "./news-desk-taxonomy-client";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";

/**
 * The site's Sections for a picker. The shell dashboard is only a summary and carries none, so when it has none this reads them
 * once, with the signed-in session, as the Sections page does. Reading fails soft: the picker then shows the Story's own value.
 */
export function useNewsroomDeskSections(): { sections: NewsroomSectionRecord[]; loading: boolean; error: string | null } {
  const session = useOptionalNewsDeskClient();
  const shellSections = session?.shell.dashboard?.newsroomSections ?? [];
  const signedIn = session?.shell.auth.status === "signedIn" && Boolean(session.shell.dashboard);
  const [loaded, setLoaded] = useState<NewsroomSectionRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const needsLoad = shellSections.length === 0 && signedIn;

  useEffect(() => {
    if (!needsLoad) return;
    let cancelled = false;
    loadEditorNewsroomSections()
      .then((rows) => { if (!cancelled) { setLoaded(rows); setError(null); } })
      .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load the sections."); });
    return () => { cancelled = true; };
  }, [needsLoad]);

  if (shellSections.length > 0) return { sections: shellSections, loading: false, error: null };
  return { sections: loaded ?? [], loading: needsLoad && loaded === null && error === null, error };
}
