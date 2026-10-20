"use client";

import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState, RangeSetBuilder, StateEffect, StateField } from "@codemirror/state";
import { Decoration, type DecorationSet, EditorView, keymap, placeholder as placeholderExtension } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { EditorialFinding } from "../lib/editorial-checks";

/** The textarea-shaped surface the article editor already drives (focus, selection, value). */
export type MarkusBodyEditorHandle = {
  readonly value: string;
  readonly selectionStart: number;
  readonly selectionEnd: number;
  focus: () => void;
  setSelectionRange: (start: number, end: number) => void;
  /** Scroll to and select a span, e.g. a finding the editor clicked in the findings panel. */
  reveal: (start: number, end: number) => void;
};

type Props = {
  value: string;
  onChange: (value: string) => void;
  findings?: EditorialFinding[];
  activeFindingId?: string | null;
  onFindingClick?: (findingId: string) => void;
  onSelectionChange?: (selection: { start: number; end: number }) => void;
  placeholder?: string;
  ariaLabel?: string;
};

type MarkedFinding = Pick<EditorialFinding, "id" | "span" | "severity" | "status" | "message">;

/** Markup is told apart by weight, emphasis and opacity, never by a fixed colour, so it reads in light and dark themes. */
const markusHighlight = HighlightStyle.define([
  { tag: tags.heading, fontWeight: "700" },
  { tag: tags.strong, fontWeight: "700" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: tags.strikethrough, textDecoration: "line-through" },
  { tag: tags.link, textDecoration: "underline" },
  { tag: [tags.url, tags.processingInstruction, tags.meta, tags.contentSeparator, tags.labelName], opacity: "0.6" },
  { tag: tags.monospace, opacity: "0.85" },
  { tag: tags.quote, fontStyle: "italic", opacity: "0.85" },
]);

const setFindings = StateEffect.define<{ findings: MarkedFinding[]; activeId: string | null }>();

function decorationsFor(findings: MarkedFinding[], activeId: string | null, length: number): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  const sorted = [...findings]
    .filter((finding) => finding.span.start < finding.span.end && finding.span.end <= length)
    .sort((a, b) => a.span.start - b.span.start || a.span.end - b.span.end);
  for (const finding of sorted) {
    builder.add(
      finding.span.start,
      finding.span.end,
      Decoration.mark({
        class: [
          "cm-editorial-finding",
          `cm-editorial-${finding.severity}`,
          `cm-editorial-${finding.status}`,
          finding.id === activeId ? "cm-editorial-active" : "",
        ].join(" "),
        attributes: { "data-editorial-finding": finding.id, title: finding.message },
      }),
    );
  }
  return builder.finish();
}

/** Findings are drawn as marks; edits move them with the text until the next check replaces them. */
const findingField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(marks, transaction) {
    let next = marks.map(transaction.changes);
    for (const effect of transaction.effects) {
      if (effect.is(setFindings)) next = decorationsFor(effect.value.findings, effect.value.activeId, transaction.state.doc.length);
    }
    return next;
  },
  provide: (field) => EditorView.decorations.from(field),
});

const theme = EditorView.theme({
  "&": { fontSize: "0.875rem", border: "1px solid var(--border)", borderRadius: "0.5rem", backgroundColor: "var(--background)", color: "var(--foreground)" },
  ".cm-cursor": { borderLeftColor: "var(--foreground)" },
  "&.cm-focused": { outline: "2px solid var(--ring)", outlineOffset: "1px" },
  ".cm-content": { fontFamily: "var(--font-mono, ui-monospace, monospace)", minHeight: "28rem", padding: "0.75rem 0" },
  ".cm-line": { padding: "0 0.75rem" },
  ".cm-editorial-finding": { textDecorationLine: "underline", textDecorationStyle: "wavy", textUnderlineOffset: "3px", cursor: "pointer" },
  ".cm-editorial-error": { textDecorationColor: "var(--destructive)" },
  ".cm-editorial-warn": { textDecorationColor: "oklch(0.75 0.16 70)" },
  ".cm-editorial-info": { textDecorationColor: "oklch(0.65 0.12 250)" },
  ".cm-editorial-review": { textDecorationStyle: "dotted" },
  ".cm-editorial-active": { backgroundColor: "color-mix(in oklch, var(--ring) 22%, transparent)" },
});

/** Replace only the stretch that differs, so finding marks elsewhere keep their place. */
export function minimalChange(before: string, after: string): { from: number; to: number; insert: string } {
  let prefix = 0;
  const limit = Math.min(before.length, after.length);
  while (prefix < limit && before.charCodeAt(prefix) === after.charCodeAt(prefix)) prefix += 1;
  let suffix = 0;
  while (
    suffix < limit - prefix &&
    before.charCodeAt(before.length - 1 - suffix) === after.charCodeAt(after.length - 1 - suffix)
  ) suffix += 1;
  return { from: prefix, to: before.length - suffix, insert: after.slice(prefix, after.length - suffix) };
}

export const MarkusBodyEditor = forwardRef<MarkusBodyEditorHandle, Props>(function MarkusBodyEditor(
  { value, onChange, findings = [], activeFindingId = null, onFindingClick, onSelectionChange, placeholder, ariaLabel = "Body" },
  ref,
) {
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<EditorView | null>(null);
  const callbacks = useRef({ onChange, onFindingClick, onSelectionChange });
  callbacks.current = { onChange, onFindingClick, onSelectionChange };

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          markdown(),
          syntaxHighlighting(markusHighlight),
          EditorView.lineWrapping,
          findingField,
          theme,
          placeholder ? placeholderExtension(placeholder) : [],
          EditorView.contentAttributes.of({
            "aria-label": ariaLabel,
            "aria-multiline": "true",
            "data-newsroom-article-body": "",
            id: "newsroom-article-body",
            spellcheck: "false",
          }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) callbacks.current.onChange(update.state.doc.toString());
            if (update.selectionSet || update.docChanged) {
              const main = update.state.selection.main;
              callbacks.current.onSelectionChange?.({ start: main.from, end: main.to });
            }
          }),
          EditorView.domEventHandlers({
            click(event) {
              const mark = (event.target as HTMLElement | null)?.closest("[data-editorial-finding]");
              const id = mark?.getAttribute("data-editorial-finding");
              if (id) callbacks.current.onFindingClick?.(id);
              return false;
            },
          }),
        ],
      }),
    });
    view.current = editor;
    // Browser specs read the document through the host element (CodeMirror only renders visible lines).
    (host.current as HTMLDivElement & { papyrusEditorValue?: () => string }).papyrusEditorValue = () => editor.state.doc.toString();
    return () => {
      editor.destroy();
      view.current = null;
    };
    // The editor is created once; `value` changes are synced below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    const current = editor.state.doc.toString();
    if (current !== value) editor.dispatch({ changes: minimalChange(current, value) });
  }, [value]);

  useEffect(() => {
    view.current?.dispatch({ effects: setFindings.of({ findings, activeId: activeFindingId }) });
  }, [findings, activeFindingId]);

  useImperativeHandle(
    ref,
    () => ({
      get value() {
        return view.current?.state.doc.toString() ?? value;
      },
      get selectionStart() {
        return view.current?.state.selection.main.from ?? 0;
      },
      get selectionEnd() {
        return view.current?.state.selection.main.to ?? 0;
      },
      focus() {
        view.current?.focus();
      },
      setSelectionRange(start: number, end: number) {
        view.current?.dispatch({ selection: { anchor: start, head: end }, scrollIntoView: true });
      },
      reveal(start: number, end: number) {
        const editor = view.current;
        if (!editor) return;
        editor.dispatch({ selection: { anchor: start, head: end }, effects: EditorView.scrollIntoView(start, { y: "center" }) });
        editor.focus();
      },
    }),
    [value],
  );

  return <div data-newsroom-article-body-editor ref={host} />;
});
