"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  feedbackFor,
  publishWarnings,
  type EditorialCheckResult,
  type EditorialFinding,
  type FeedbackDecision,
  type RewriteResult,
  type Span,
} from "../lib/editorial-checks";
import type { EditorialChecksBackend } from "../lib/editorial-checks-backend";
import { DEFAULT_EDITORIAL_SETTINGS, type EditorialSettings } from "../lib/editorial-checks-settings";
import type { CheckStatus } from "./editorial-findings-panel";

const CHECK_PAUSE_MS = 2000;

/**
 * Editorial checks for one article body. A result only applies to the exact body
 * it was computed for: if the editor typed while the check ran, the result is
 * dropped and the next pause checks again.
 */
export function useEditorialChecks({
  backend,
  body,
  section,
  itemId,
}: {
  /** null when there is no backend to check against (a preview). Whether a publication runs checks is its stored setting. */
  backend: EditorialChecksBackend | null;
  body: string | null;
  section: string;
  itemId: string | null;
}) {
  const available = backend !== null;
  const [settings, setSettings] = useState<EditorialSettings>(DEFAULT_EDITORIAL_SETTINGS);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const enabled = available && settings.enabled;
  const [result, setResult] = useState<EditorialCheckResult | null>(null);
  const [checkedBody, setCheckedBody] = useState<string | null>(null);
  const [status, setStatus] = useState<CheckStatus>({ state: "idle" });
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const [activeFindingId, setActiveFindingId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Span>({ start: 0, end: 0 });
  const latestBody = useRef(body);
  latestBody.current = body;
  const sequence = useRef(0);

  useEffect(() => {
    if (!available) return;
    backend?.loadSettings().then(({ settings: loaded }) => setSettings(loaded)).catch(() => undefined).finally(() => setSettingsLoaded(true));
  }, [available, backend]);

  useEffect(() => {
    if (!enabled || !itemId) return;
    backend?.dismissedFindingIds(itemId).then(setDismissed).catch(() => undefined);
  }, [backend, enabled, itemId]);

  const check = useCallback(async () => {
    const text = latestBody.current;
    if (!backend || !enabled || text === null || !text.trim()) return;
    const run = ++sequence.current;
    setStatus({ state: "checking" });
    try {
      const checked = await backend.check(text, section.trim() || null);
      if (run !== sequence.current) return;
      if (latestBody.current !== text) {
        setStatus({ state: "idle" });
        return;
      }
      setResult(checked);
      setCheckedBody(text);
      setStatus({ state: "idle" });
    } catch (error) {
      if (run === sequence.current) setStatus({ state: "error", message: error instanceof Error ? error.message : "The check failed." });
    }
  }, [backend, enabled, section]);

  useEffect(() => {
    if (!enabled || !settingsLoaded || !settings.checkWhileTyping || body === null || body === checkedBody) return;
    const timer = window.setTimeout(() => void check(), CHECK_PAUSE_MS);
    return () => window.clearTimeout(timer);
  }, [body, check, checkedBody, enabled, settings.checkWhileTyping, settingsLoaded]);

  const record = useCallback(
    (finding: EditorialFinding, decision: FeedbackDecision, reason: string | null = null) => {
      if (!result || checkedBody === null) return;
      void backend?.recordFeedback(feedbackFor(result, checkedBody, finding, decision, itemId, reason)).catch(() => undefined);
    },
    [backend, checkedBody, itemId, result],
  );

  const dismiss = useCallback(
    (finding: EditorialFinding, reason: string) => {
      record(finding, "dismissed", reason);
      setDismissed((current) => new Set(current).add(finding.id));
    },
    [record],
  );

  const suggest = useCallback(
    (target: { finding: EditorialFinding } | { selection: Span }, note: string | null): Promise<RewriteResult> =>
      backend
        ? backend.suggest(latestBody.current ?? "", section.trim() || null, target, note)
        : Promise.reject(new Error("Editorial checks are off.")),
    [backend, section],
  );

  const current = enabled && result && checkedBody === body;
  return {
    enabled,
    settings,
    result,
    /** Findings whose spans still match the body on screen. */
    inlineResult: current ? result : null,
    status,
    dismissed,
    activeFindingId,
    setActiveFindingId,
    selection,
    setSelection,
    check,
    suggest,
    dismiss,
    accept: (finding: EditorialFinding) => record(finding, "accepted"),
    fixed: (finding: EditorialFinding) => {
      record(finding, "fixed");
      setDismissed((current) => new Set(current).add(finding.id));
    },
    openWarnings: enabled && settings.publishWarning && result ? publishWarnings(result.findings, dismissed) : [],
  };
}
