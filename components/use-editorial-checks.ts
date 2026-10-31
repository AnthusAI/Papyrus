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

/** Checks run on their own unless a publication's stored settings say `checkWhileTyping: false`; absent or null means on. */
export function runsAutomatically(settings: Pick<EditorialSettings, "checkWhileTyping"> | null | undefined): boolean {
  return settings?.checkWhileTyping !== false;
}

/** What a check was computed for. The same body in another section is a different check (the section picks the policies). */
export function checkKey(body: string, section: string): string {
  return `${section.trim()}\u0000${body}`;
}

/**
 * Editorial checks for one article body. A result only applies to the exact body
 * and section it was computed for. Checks run by themselves a pause after the
 * body or section changes, one at a time: if the editor typed while a check ran,
 * its result is dropped and the next pause checks the latest text. After a save
 * the pending check runs at once and the saved version is checked on the server
 * (which skips content it has already checked).
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
  const [checkedKey, setCheckedKey] = useState<string | null>(null);
  /** The text a check failed on: it is not retried by itself (that would loop on a provider outage), only when the text changes or the editor asks. */
  const [failedKey, setFailedKey] = useState<string | null>(null);
  const [saveRevision, setSaveRevision] = useState(0);
  const [status, setStatus] = useState<CheckStatus>({ state: "idle" });
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const [activeFindingId, setActiveFindingId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Span>({ start: 0, end: 0 });
  const latestBody = useRef(body);
  latestBody.current = body;
  const sectionName = section.trim();
  const latestSection = useRef(sectionName);
  latestSection.current = sectionName;
  const key = body === null ? null : checkKey(body, sectionName);
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
    const sectionAtStart = latestSection.current;
    if (!backend || !enabled || text === null || !text.trim()) return;
    const checking = checkKey(text, sectionAtStart);
    const run = ++sequence.current;
    setStatus({ state: "checking" });
    try {
      const checked = await backend.check(text, sectionAtStart || null);
      if (run !== sequence.current) return;
      if (latestBody.current !== text || latestSection.current !== sectionAtStart) {
        setStatus({ state: "idle" });
        return;
      }
      setResult(checked);
      setCheckedBody(text);
      setCheckedKey(checking);
      setFailedKey(null);
      setStatus({ state: "idle" });
    } catch (error) {
      if (run === sequence.current) {
        setFailedKey(checking);
        setStatus({ state: "error", message: error instanceof Error ? error.message : "The check failed." });
      }
    }
  }, [backend, enabled]);

  const auto = enabled && settingsLoaded && runsAutomatically(settings);
  const pending = key !== null && key !== checkedKey && key !== failedKey && body !== null && body.trim() !== "";
  const inFlight = status.state === "checking";
  useEffect(() => {
    if (!auto || !pending || inFlight) return;
    const timer = window.setTimeout(() => void check(), CHECK_PAUSE_MS);
    return () => window.clearTimeout(timer);
  }, [auto, check, inFlight, key, pending]);

  // A save runs whatever is pending now instead of waiting for the pause.
  useEffect(() => {
    if (saveRevision === 0 || !auto || !pending || inFlight) return;
    void check();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saveRevision]);

  /** Call after a version is saved: check what is pending now, and have the server check and store the saved version. */
  const afterSave = useCallback(
    (savedItemId: string | null) => {
      setSaveRevision((revision) => revision + 1);
      if (!enabled || !savedItemId || !backend?.checkVersion) return;
      void backend.checkVersion(savedItemId).catch(() => undefined);
    },
    [backend, enabled],
  );

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

  const current = enabled && result && checkedKey === key;
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
    afterSave,
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
