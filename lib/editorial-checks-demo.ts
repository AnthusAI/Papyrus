/**
 * Demo-mode editorial checks: no backend, a few stock phrases, canned rewrites.
 * The shapes match Limatus results so the editor, the preview marks and the
 * rewrite flow behave as they do against the real backend.
 */
import type { EditorialCheckResult, EditorialFinding, EditorialSegment, RewriteResult, Span } from "./editorial-checks";
import type { EditorialChecksBackend } from "./editorial-checks-backend";
import { DEFAULT_EDITORIAL_SETTINGS } from "./editorial-checks-settings";

type DemoRule = { policyId: string; phrase: RegExp; severity: EditorialFinding["severity"]; message: string; replacement?: string };

const RULES: DemoRule[] = [
  { policyId: "promotional-language", phrase: /\bgame[- ]changing\b/gi, severity: "warn", message: "Say what changed instead of calling it game-changing." },
  { policyId: "plain-words", phrase: /\butilize\b/gi, severity: "info", message: "Prefer the plain word.", replacement: "use" },
  { policyId: "formulaic-openers", phrase: /\bIn today's [a-z-]+ world\b/gi, severity: "info", message: "Formulaic opener: start with the point." },
];

/** Demo rewrites keyed by a phrase in the target; anything else gets a clearly labelled placeholder. */
const CANNED: Record<string, string[]> = {
  "game-changing": ["Our caching layer cuts build times for teams.", "Teams get faster builds from our caching layer."],
  "Builds finish in 4 minutes": ["Builds now take 4 minutes, down from 9.", "A build takes 4 minutes instead of 9."],
};

export function demoPlainText(source: string): string {
  return source
    .replace(/^#{1,6}\s+/, "")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\s?\[@[^\]]+\]/g, "")
    .replace(/(\*\*|__|\*|_|~~|`)/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function hash(text: string): string {
  let value = 0;
  for (let i = 0; i < text.length; i += 1) value = (value * 31 + text.charCodeAt(i)) >>> 0;
  return value.toString(16).padStart(8, "0");
}

/** Paragraph and sentence segments of a body, by blank lines and sentence-ending punctuation. */
export function demoSegments(body: string): EditorialSegment[] {
  const segments: EditorialSegment[] = [{ id: "doc", kind: "document", start: 0, end: body.length, textHash: hash(body) }];
  const fence = /^(```|~~~)/;
  let inFence = false;
  for (const match of body.matchAll(/[^\n]+(?:\n[^\n]+)*/g)) {
    const raw = match[0];
    const start = match.index ?? 0;
    if (fence.test(raw.trim())) inFence = !inFence;
    if (inFence || fence.test(raw.trim()) || /^(:::|::|>|\||---)/.test(raw.trim())) continue;
    const block = raw.trim().startsWith("#") ? "heading" : /^([-*+]|\d+\.)\s/.test(raw.trim()) ? "listItem" : "paragraph";
    const sourceStart = start + raw.length - raw.replace(/^(#{1,6}|[-*+]|\d+\.)\s+/, "").length;
    const text = demoPlainText(raw);
    const paragraphId = `p-${hash(text)}`;
    segments.push({ id: paragraphId, kind: "paragraph", block, start: sourceStart, end: start + raw.length, textHash: hash(text), text });
    const sentencePattern = /[^.!?]+[.!?]+(?=\s|$)|[^.!?]+$/g;
    for (const sentence of body.slice(sourceStart, start + raw.length).matchAll(sentencePattern)) {
      const leading = sentence[0].length - sentence[0].trimStart().length;
      const sStart = sourceStart + (sentence.index ?? 0) + leading;
      const sText = sentence[0].trim();
      if (!sText) continue;
      segments.push({
        id: `s-${hash(sText)}`,
        kind: "sentence",
        block,
        parentId: paragraphId,
        start: sStart,
        end: sStart + sText.length,
        textHash: hash(sText),
        text: demoPlainText(sText),
      });
    }
  }
  return segments;
}

export function demoCheck(body: string): EditorialCheckResult {
  const segments = demoSegments(body);
  const sentences = segments.filter((segment) => segment.kind === "sentence");
  const findings: EditorialFinding[] = [];
  for (const rule of RULES) {
    for (const match of body.matchAll(rule.phrase)) {
      const start = match.index ?? 0;
      const end = start + match[0].length;
      const sentence = sentences.find((segment) => segment.start <= start && end <= segment.end);
      if (!sentence) continue;
      findings.push({
        id: `f-${hash(`${rule.policyId}|${sentence.text}|${match[0]}`)}${hash(String(start)).slice(0, 8)}`,
        policyId: rule.policyId,
        policyVersion: 1,
        detectorId: `${rule.policyId}-demo`,
        lane: "rules",
        severity: rule.severity,
        status: "violation",
        segmentId: sentence.id,
        span: { start, end },
        excerpt: match[0],
        excerptText: match[0],
        message: rule.message,
        ...(rule.replacement ? { replacement: rule.replacement } : {}),
      });
    }
  }
  return {
    schemaVersion: 1,
    offsetUnit: "utf16",
    document: { hash: `demo:${hash(body)}`, length: body.length },
    pack: { packId: "demo", version: "1" },
    segments,
    protected: [],
    findings: findings.sort((a, b) => a.span.start - b.span.start),
    coverage: [],
    lanes: { rules: { status: "ran", detectors: RULES.length }, classifier: { status: "disabled" } },
  };
}

export function demoSuggest(body: string, target: { finding: EditorialFinding } | { selection: Span }): RewriteResult {
  let span: Span;
  if ("finding" in target) {
    const sentence = demoSegments(body).find((s) => s.kind === "sentence" && s.start <= target.finding.span.start && target.finding.span.end <= s.end);
    span = sentence ? { start: sentence.start, end: sentence.end } : target.finding.span;
  } else {
    span = target.selection;
  }
  const excerpt = body.slice(span.start, span.end);
  const replacements = Object.entries(CANNED).find(([phrase]) => excerpt.includes(phrase))?.[1] ?? [`${demoPlainText(excerpt)} (demo rewrite)`];
  return {
    target: { ...("finding" in target ? { findingId: target.finding.id } : {}), span, excerpt },
    model: "demo",
    options: replacements.map((replacement, index) => ({
      id: `o-demo-${index}`,
      span,
      replacement,
      rationale: index === 0 ? "Says what changed, plainly." : "An alternative phrasing.",
      factVerificationRequired: false,
      unresolvedQuestions: [],
    })),
  };
}

export const demoEditorialBackend: EditorialChecksBackend = {
  loadSettings: async () => ({ settings: DEFAULT_EDITORIAL_SETTINGS, exists: false }),
  dismissedFindingIds: async () => new Set(),
  check: async (body) => demoCheck(body),
  suggest: async (body, _section, target) => demoSuggest(body, target),
  recordFeedback: async () => undefined,
};
