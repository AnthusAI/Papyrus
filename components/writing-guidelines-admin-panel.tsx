"use client";

/**
 * Administration > Policies > Writing guidelines: the publication's house voice as data, beside Visual style. A Site tab and one tab per section; a section tab
 * shows the effective guidelines with a word on every field for where it came from (Site, This section, Locked by site). Every read and write goes through the
 * guidelines door's operations; nothing here knows how a document is stored. Flat backgrounds and rounded shapes only, Lucide icons only, and every state is an
 * icon plus a word. Design: docs/plans/guidelines-as-data.md section 8.
 */
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpen, Check, ChevronDown, ChevronUp, CircleAlert, CircleCheck, Eye, FilePenLine, FilePlus, FileText, FileX, History, Info, Layers, Link as LinkIcon, ListChecks, Loader, Lock, OctagonAlert, PenLine,
  Plus, Search, Trash2, TriangleAlert, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { listPolicies } from "../lib/editorial-checks-client";
import { guidelinesDoor, listPublishedStories } from "../lib/guidelines/guidelines-door-client";
import {
  FIELD_FILES, FILE_NAME, SEVERITIES, SEVERITY_HINTS, SEVERITY_WORDS, STATE_WORDS, addableFieldFiles, changedCount, checkKey, exemplarsBody, exemplarsOf, fieldFileNamed, filesFrom, folderNames,
  foldersOf, isDecidable, lines, linesOf, lockedInFiles, lockedKeys, maxLengthOf, newFieldFile, newRuleFile, newRuleName, pathOf, restoreFolder, ruleFileChanges, severityOf, stateOf, textOf, withBody,
  withMeta, withoutFolder, type FieldFile, type FileState, type Folder, type Scalar,
} from "../lib/guidelines/guideline-files";
import {
  EDITORS_READ_ONLY, FIELD_LABELS, NO_WRITING_WARNING, SITE_TAB, derivedChecks, describeChange, diffDocuments, matchStories, reasonProblem, sourceWords, storyTitle, valueWords,
  type FieldSources, type GuidelineDocument, type GuidelinesDoor, type ListPublishedStories, type PublishedStory,
} from "../lib/guidelines/writing-guidelines-admin";

export type GuidelineSection = { key: string; name: string };
type Version = { itemId: string; versionNumber: number; isCurrent?: boolean; at?: string; by?: string; byKind?: string; reason?: string };
type Loaded = { status: "loading" } | { status: "error"; message: string } | { status: "none"; guard: string }
  | { status: "ready"; document: GuidelineDocument; files: Record<string, string>; guard: string; versionNumber: number; updatedBy: string; updatedAt: string };
type Note = { tone: "ok" | "error" | "info"; text: string };
type Page = "edit" | "effective" | "history";
type CheckRow = { id: string; title: string; enabled: boolean; source: string; policyKey?: string };

const FIELD = "w-full vs-tile bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-70";
const PANEL = "vs-panel bg-muted/60 p-4";

function StatusLine({ note }: { note: Note | null }) {
  return (
    <div aria-live="polite" className="flex items-center gap-2 text-sm" data-writing-guidelines-status role="status">
      {note ? (note.tone === "error" ? <CircleAlert aria-hidden className="size-4" /> : note.tone === "ok" ? <CircleCheck aria-hidden className="size-4" /> : <Info aria-hidden className="size-4" />) : null}
      {note ? <span><strong>{note.tone === "error" ? "Problem: " : note.tone === "ok" ? "Done: " : ""}</strong>{note.text}</span> : null}
    </div>
  );
}

function SourceTag({ field, words }: { field: string; words: string }) {
  return (
    <span className="inline-flex items-center gap-1 vs-pill bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground" data-field-source={field}>
      {words === "Locked by site" ? <Lock aria-hidden className="size-3" /> : <Layers aria-hidden className="size-3" />}Source: {words}
    </span>
  );
}

export function WritingGuidelinesAdmin({ door = guidelinesDoor, listStories = listPublishedStories, listChecks = realChecks, sections = [], isAdmin = false, checksHref = "/newsroom/administration/editorial-checks" }: {
  door?: GuidelinesDoor; listStories?: ListPublishedStories; listChecks?: () => Promise<CheckRow[]>; sections?: GuidelineSection[]; isAdmin?: boolean; checksHref?: string;
}) {
  const [tab, setTab] = useState<string>(SITE_TAB);
  const [page, setPage] = useState<Page>("edit");
  const [site, setSite] = useState<Loaded>({ status: "loading" });
  const [own, setOwn] = useState<Loaded>({ status: "loading" });
  const [resolved, setResolved] = useState<{ document: GuidelineDocument; fieldSources: FieldSources } | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [checks, setChecks] = useState<CheckRow[] | null>(null);
  const section = tab === SITE_TAB ? null : tab;
  const sectionName = sections.find((item) => item.key === tab)?.name ?? tab;

  const read = useCallback(async (sectionKey: string | null): Promise<Loaded> => {
    try {
      const answer = await door("guidelines_get", { kind: "writing", ...(sectionKey ? { section: sectionKey } : {}) });
      if (answer.ok) {
        const result = answer.result;
        return { status: "ready", document: result.document, files: filesFrom(result.files), guard: result.expectedCurrentVersionId, versionNumber: result.versionNumber, updatedBy: result.updatedBy ?? "", updatedAt: result.updatedAt ?? "" };
      }
      if (answer.error.code === "not_found") return { status: "none", guard: "none" };
      return { status: "error", message: answer.error.message };
    } catch (error) {
      return { status: "error", message: error instanceof Error ? error.message : "Could not load the writing guidelines." };
    }
  }, [door]);

  const load = useCallback(async () => {
    const siteAnswer = await read(null);
    setSite(siteAnswer);
    if (!section) { setOwn(siteAnswer); setResolved(null); return; }
    setOwn(await read(section));
    try {
      const answer = await door("guidelines_resolve", { kind: "writing", section });
      setResolved(answer.ok ? { document: answer.result.document, fieldSources: answer.result.fieldSources as FieldSources } : null);
    } catch { setResolved(null); }
  }, [door, read, section]);
  useEffect(() => { setOwn({ status: "loading" }); void load(); }, [load]);

  const siteDocument = site.status === "ready" ? site.document : null;
  const checksKey = own.status === "ready" ? own.versionNumber : 0;
  useEffect(() => { let live = true; void listChecks().then((all) => { if (live) setChecks(derivedChecks(all, section)); }).catch(() => { if (live) setChecks([]); }); return () => { live = false; }; }, [listChecks, section, checksKey]);

  if (site.status === "loading") return <p className="flex items-center gap-2" data-writing-guidelines="loading" role="status"><Loader aria-hidden className="size-4 animate-spin" /> Loading the writing guidelines…</p>;
  if (site.status === "error") return <p className="flex items-center gap-2" data-writing-guidelines="error" role="alert"><CircleAlert aria-hidden className="size-4" /> <strong>Problem:</strong> {site.message}</p>;

  return (
    <section aria-labelledby="writing-guidelines-title" className="space-y-5" data-news-desk-admin-panel="writing-guidelines">
      <header className="space-y-1">
        <h3 className="flex items-center gap-2 text-lg font-semibold" id="writing-guidelines-title"><PenLine aria-hidden className="size-5" /> Writing guidelines</h3>
        <p className="text-sm text-muted-foreground">
          How this publication writes, saved once so editors, agents and the editorial checks follow the same voice. {site.status === "ready"
            ? `Site version ${site.versionNumber}, last changed by ${site.updatedBy || "someone"}.` : "There are no site guidelines yet."}
        </p>
        {!isAdmin ? <p className="flex items-center gap-2 text-sm" data-writing-guidelines-readonly><Eye aria-hidden className="size-4" /> <strong>Read only:</strong> {EDITORS_READ_ONLY}</p> : null}
        {site.status === "none" ? <p className="flex items-center gap-2 text-sm" data-writing-guidelines-warning role="alert"><CircleAlert aria-hidden className="size-4" /> {NO_WRITING_WARNING}</p> : null}
      </header>

      <nav aria-label="Writing guidelines tabs" className="flex flex-wrap gap-2" data-writing-guidelines-tabs>
        {[{ key: SITE_TAB, name: "Site" }, ...sections].map((item) => (
          <Button aria-pressed={tab === item.key} data-writing-guidelines-tab={item.key} key={item.key} onClick={() => { setTab(item.key); setPage("edit"); setNote(null); }} type="button" variant={tab === item.key ? "default" : "secondary"}>
            {item.key === SITE_TAB ? <PenLine aria-hidden /> : <Layers aria-hidden />}{item.name}{tab === item.key ? <span className="sr-only"> (selected)</span> : null}
          </Button>
        ))}
      </nav>

      <nav aria-label="Writing guidelines pages" className="flex flex-wrap gap-2" data-writing-guidelines-pages>
        <Button aria-pressed={page === "edit"} data-writing-guidelines-page="edit" onClick={() => setPage("edit")} size="sm" type="button" variant={page === "edit" ? "default" : "secondary"}><FilePenLine aria-hidden /> {isAdmin ? "Edit" : "Read"}{page === "edit" ? <span className="sr-only"> (selected)</span> : null}</Button>
        {section ? <Button aria-pressed={page === "effective"} data-writing-guidelines-page="effective" onClick={() => setPage("effective")} size="sm" type="button" variant={page === "effective" ? "default" : "secondary"}><ListChecks aria-hidden /> In effect{page === "effective" ? <span className="sr-only"> (selected)</span> : null}</Button> : null}
        <Button aria-pressed={page === "history"} data-writing-guidelines-page="history" onClick={() => setPage("history")} size="sm" type="button" variant={page === "history" ? "default" : "secondary"}><History aria-hidden /> History{page === "history" ? <span className="sr-only"> (selected)</span> : null}</Button>
      </nav>
      <StatusLine note={note} />

      {page === "edit" ? (
        <EditPage door={door} drawn={checks} isAdmin={isAdmin} key={tab} listStories={listStories} loaded={own} onSaved={async (text) => { await load(); setNote({ tone: "ok", text }); }} section={section} setNote={setNote} siteDocument={siteDocument} sectionName={sectionName} />
      ) : null}
      {page === "effective" && section ? <EffectivePage own={own} resolved={resolved} sectionName={sectionName} siteDocument={siteDocument} /> : null}
      {page === "history" ? <HistoryPage door={door} section={section} /> : null}
      <ChecksList checksHref={checksHref} rows={checks} />
    </section>
  );
}

// --- editing: the set of guideline files ------------------------------------------------------------------------------------------------------------

type Preview = { files: string[]; fields: string[]; checks: string[] };
type PlanStep = { action: string; policy: string };

const SEVERITY_ICON = { error: OctagonAlert, warn: TriangleAlert, guidance: BookOpen } as const;
const STATE_ICON = { unchanged: Check, changed: PenLine, added: FilePlus, removed: FileX } as const;
const CHANGE_WORDS = { added: "added", changed: "changed", removed: "removed" } as const;

const PILL = "inline-flex items-center gap-1 vs-pill bg-secondary px-2.5 py-0.5 font-medium text-secondary-foreground";
function Pill({ children, ...rest }: { children: ReactNode; [attribute: `data-${string}`]: string | boolean | undefined }) { return <span className={PILL} {...rest}>{children}</span>; }

/** A box of one value per line that keeps what is typed (an empty line while typing) and follows the file when it is rejected or reset. */
function LineBox({ disabled, value, onLines }: { disabled: boolean; value: string[]; onLines: (lines: string[]) => void }) {
  const [text, setText] = useState(value.join("\n"));
  useEffect(() => { if (JSON.stringify(lines(text)) !== JSON.stringify(value)) setText(value.join("\n")); }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return <textarea className={FIELD} disabled={disabled} onChange={(event) => { setText(event.target.value); onLines(lines(event.target.value)); }} rows={3} value={text} />;
}

function Labelled({ label, hint, children, field }: { label: string; hint?: string; children: React.ReactNode; field: string }) {
  return (
    <label className="block space-y-1" data-field={field}>
      <span className="block text-sm font-medium">{label}</span>
      {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      {children}
    </label>
  );
}

function problemsOf(details: Record<string, unknown> | undefined): Record<string, string[]> {
  const found: Record<string, string[]> = {};
  const list = Array.isArray(details?.problems) ? (details!.problems as Record<string, unknown>[]) : [];
  for (const problem of list) {
    const folder = typeof problem.guideline === "string" ? problem.guideline : "";
    const key = typeof problem.key === "string" && problem.key ? `${problem.key} ` : "";
    (found[folder] ??= []).push(`${key}${typeof problem.message === "string" ? problem.message : "has a problem"}`);
  }
  return found;
}

function EditPage({ door, drawn, isAdmin, listStories, loaded, onSaved, section, sectionName, setNote, siteDocument }: {
  door: GuidelinesDoor; drawn: CheckRow[] | null; isAdmin: boolean; listStories: ListPublishedStories; loaded: Loaded; onSaved: (text: string) => Promise<void>; section: string | null; sectionName: string;
  setNote: (note: Note | null) => void; siteDocument: GuidelineDocument | null;
}) {
  const saved = useMemo(() => (loaded.status === "ready" ? loaded.files : {}), [loaded]);
  const [draft, setDraft] = useState<Record<string, string>>(saved);
  const [open, setOpen] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [problems, setProblems] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const [stories, setStories] = useState<PublishedStory[] | null>(null);
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState<string | null>(null);
  const versionKey = loaded.status === "ready" ? loaded.versionNumber : loaded.status;
  useEffect(() => { setDraft(saved); setReason(""); setPreview(null); setProblems({}); setAdding(null); }, [versionKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (isAdmin) void listStories().then(setStories).catch(() => setStories([])); }, [isAdmin, listStories]);

  const guard = loaded.status === "ready" || loaded.status === "none" ? loaded.guard : "none";
  const lockedHere = useMemo(() => (section ? lockedKeys(siteDocument) : []), [section, siteDocument]);
  const lockedForSections = useMemo(() => lockedInFiles(draft), [draft]);
  const names = useMemo(() => folderNames(saved, draft), [saved, draft]);
  const items = useMemo(() => foldersOf(draft), [draft]);
  const changed = changedCount(saved, draft);
  const disabled = !isAdmin || busy;

  const edit = (next: Record<string, string>) => { setDraft(next); setPreview(null); setProblems({}); };
  const update = (item: Folder, text: string) => edit({ ...draft, [pathOf(item.folder)]: text });
  const toggle = (folder: string) => setOpen((current) => (current.includes(folder) ? current.filter((name) => name !== folder) : [...current, folder]));
  const reject = (folder: string) => edit(restoreFolder(draft, saved, folder));
  const remove = (folder: string) => { edit(withoutFolder(draft, folder)); setOpen((current) => current.filter((name) => name !== folder)); };

  const request = () => ({ kind: "writing", ...(section ? { section } : {}), files: draft as Record<string, unknown> });
  const refused = (error: { message: string; details: Record<string, unknown> }) => { setProblems(problemsOf(error.details)); setNote({ tone: "error", text: error.message }); };

  const showChanges = async () => {
    setBusy(true); setNote(null);
    try {
      const answer = await door("guidelines_diff", request());
      if (!answer.ok) { refused(answer.error); return; }
      const result = answer.result as typeof answer.result & { policyPlan?: PlanStep[] };
      setPreview({
        files: (result.fileChanges ?? []).map((change) => `${change.path} ${CHANGE_WORDS[change.change]}`), fields: result.changes.map(describeChange),
        checks: (result.policyPlan ?? []).filter((step) => step.action !== "unchanged" && step.action !== "skipped").map((step) => `Check ${step.policy}: ${step.action}`),
      });
    } catch (error) { setNote({ tone: "error", text: error instanceof Error ? error.message : "Could not work out what would change." }); } finally { setBusy(false); }
  };

  const save = async () => {
    const problem = reasonProblem(reason);
    if (problem) { setNote({ tone: "error", text: problem }); return; }
    setBusy(true); setNote(null);
    try {
      const answer = await door("guidelines_save", { ...request(), reason: reason.trim(), expectedCurrentVersionId: guard });
      if (!answer.ok) {
        if (answer.error.code === "stale_version") { setNote({ tone: "error", text: "Someone else changed the guidelines while you were editing. They have been reloaded; make your change again." }); await onSaved("The latest guidelines are loaded."); return; }
        refused(answer.error); return;
      }
      await onSaved(answer.result.unchanged ? "Nothing changed, so no new version was made." : `Saved as version ${answer.result.versionNumber}.`);
    } catch (error) { setNote({ tone: "error", text: error instanceof Error ? error.message : "The guidelines could not be saved." }); } finally { setBusy(false); }
  };

  const addRule = () => {
    const name = (adding ?? "").trim();
    if (newRuleName(name, names) !== null) return;
    edit({ ...draft, [pathOf(name)]: newRuleFile(name, section) });
    setOpen((current) => [...current, name]); setAdding(null);
  };
  const addField = (field: FieldFile) => { edit({ ...draft, [pathOf(field.name)]: newFieldFile(field, section) }); setOpen((current) => [...current, field.name]); };

  if (loaded.status === "loading") return <p className="flex items-center gap-2" role="status"><Loader aria-hidden className="size-4 animate-spin" /> Loading…</p>;
  if (loaded.status === "error") return <p className="flex items-center gap-2" role="alert"><CircleAlert aria-hidden className="size-4" /> <strong>Problem:</strong> {loaded.message}</p>;

  const ruleProblem = adding === null ? null : newRuleName(adding, names);
  const addable = addableFieldFiles(new Set(names), section, lockedHere);
  const lockedMissing = FIELD_FILES.filter((field) => lockedHere.includes(field.key) && !names.includes(field.name));
  return (
    <div className="space-y-4" data-writing-guidelines-page-body="edit">
      {section ? <p className="flex items-start gap-2 text-sm" data-section-explainer><Info aria-hidden className="mt-0.5 size-4 shrink-0" /> <span>These are the files for <strong>{sectionName}</strong>. They are laid over the site&apos;s guidelines: prose and word lists add to the site&apos;s, and a choice replaces the site&apos;s unless the site locks it. See the In effect page for the result.</span></p> : null}
      {loaded.status === "none" && Object.keys(draft).length === 0 ? <p className="text-sm text-muted-foreground" data-no-document>{section ? "This section has no files yet, so it follows the site's guidelines." : "Nothing is saved yet. The first save makes version 1."}</p> : null}

      <div className={`${PANEL} space-y-3`} data-guideline-files>
        <h4 className="flex items-center gap-2 font-semibold"><FileText aria-hidden className="size-4" /> Guideline files</h4>
        <p className="text-xs text-muted-foreground">Each file is one guideline: front matter, then the prose. A field file (tone, audience, lexicon...) is part of the house style. A rule file has a severity: an error or a warning derives an editorial check, guidance does not.</p>
        {names.length === 0 ? <p className="text-sm text-muted-foreground">There are no files yet.</p> : null}
        <ul className="space-y-2">
          {names.map((folder) => {
            const state = stateOf(folder, saved, draft);
            const item = items.find((entry) => entry.folder === folder) ?? foldersOf(saved).find((entry) => entry.folder === folder)!;
            const field = fieldFileNamed(folder);
            const locked = Boolean(field && lockedHere.includes(field.key));
            const isOpen = open.includes(folder) && state !== "removed";
            return <FileCard changeState={state} disabled={disabled || locked} drawn={drawn} editable={isAdmin && !locked} field={field} isOpen={isOpen} item={item} key={folder} locked={locked}
              lockedForSections={Boolean(field && !section && lockedForSections.includes(field.key))} onReject={() => reject(folder)} onRemove={() => remove(folder)} onToggle={() => toggle(folder)}
              onUpdate={(text) => update(item, text)} problems={problems[folder] ?? []} query={query} savedItem={foldersOf(saved).find((entry) => entry.folder === folder) ?? null}
              setQuery={setQuery} siteValue={section && field ? valueWords(siteDocument?.[field.key]) : ""} stories={stories} />;
          })}
        </ul>
        {lockedMissing.length ? (
          <ul className="space-y-1" data-locked-fields>
            {lockedMissing.map((field) => <li className="flex items-center gap-2 vs-tile bg-background px-3 py-2 text-sm" data-locked-field={field.key} key={field.key}><Lock aria-hidden className="size-4" /> {field.label}: Locked by site, so this section cannot add it.</li>)}
          </ul>
        ) : null}
        {isAdmin ? (
          <div className="space-y-3" data-add-files>
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button data-add-rule disabled={busy} onClick={() => setAdding(adding === null ? "" : null)} size="sm" type="button" variant="secondary"><FilePlus aria-hidden /> Add a rule file</Button>
              </div>
              {adding !== null ? (
                <div className="space-y-1" data-new-rule>
                  <label className="block space-y-1"><span className="text-sm font-medium">Name of the rule (the folder it lives in)</span>
                    <input className={FIELD} data-new-rule-name onChange={(event) => setAdding(event.target.value)} placeholder="plain-claims" value={adding} /></label>
                  {adding.trim() && ruleProblem ? <p className="flex items-center gap-2 text-sm" data-new-rule-problem role="alert"><CircleAlert aria-hidden className="size-4" /> {ruleProblem}</p> : null}
                  <Button data-new-rule-add disabled={ruleProblem !== null} onClick={addRule} size="sm" type="button"><Plus aria-hidden /> Add the file</Button>
                </div>
              ) : null}
            </div>
            {addable.length ? (
              <div className="space-y-1">
                <p className="text-sm font-medium">Add a field file</p>
                <div className="flex flex-wrap gap-2">
                  {addable.map((field) => <Button data-add-field-file={field.name} disabled={busy} key={field.name} onClick={() => addField(field)} size="sm" type="button" variant="secondary"><Plus aria-hidden /> {field.label}</Button>)}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {isAdmin ? (
        <div className={`${PANEL} space-y-3`} data-save-bar>
          <label className="block space-y-1"><span className="text-sm font-medium">Why are you changing the guidelines? (required)</span>
            <input className={FIELD} data-save-reason onChange={(event) => setReason(event.target.value)} placeholder="For example: tighten the tone after the style review" value={reason} />
          </label>
          <p className="flex items-center gap-2 text-sm" data-change-count><PenLine aria-hidden className="size-4" /> {changed === 0 ? "No file has changed." : `${changed} ${changed === 1 ? "file has" : "files have"} changed.`}</p>
          {preview ? (
            <div data-change-preview>
              <p className="text-sm font-medium">{preview.files.length + preview.fields.length + preview.checks.length ? "Saving would change:" : "Nothing would change."}</p>
              <ul className="list-disc pl-5 text-sm">{[...preview.files, ...preview.fields, ...preview.checks].map((line) => <li key={line}>{line}</li>)}</ul>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button data-show-changes disabled={busy} onClick={() => void showChanges()} type="button" variant="secondary"><Eye aria-hidden /> Show what would change</Button>
            <Button data-save disabled={busy || reasonProblem(reason) !== null} onClick={() => void save()} type="button"><Check aria-hidden /> Accept and save as a new version</Button>
            <Button data-reject-all disabled={busy || changed === 0} onClick={() => edit(saved)} type="button" variant="secondary"><X aria-hidden /> Reject all changes</Button>
          </div>
          {reasonProblem(reason) ? <p className="flex items-center gap-2 text-sm text-muted-foreground" data-reason-needed><Info aria-hidden className="size-4" /> Saving is possible once you give a reason.</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function checkLine(item: Folder, savedItem: Folder | null, drawn: CheckRow[] | null): string {
  if (item.role === "field") return "Part of the house style: writers and agents read it.";
  const severity = severityOf(item);
  if (severity === "guidance") return "Guidance only: no check is derived.";
  const judgement = isDecidable(item) ? "" : " It needs judgement: the check shows the guideline to the writer and the editor and finds nothing by itself.";
  const row = drawn?.find((entry) => entry.policyKey === checkKey(item));
  if (savedItem && severityOf(savedItem) === severity && row) return `Derived check: ${row.title} (${row.enabled ? "on" : "off"}).${judgement}`;
  return `A check is derived when you save.${judgement}`;
}

function FileCard({ changeState, disabled, drawn, editable, field, isOpen, item, locked, lockedForSections, onReject, onRemove, onToggle, onUpdate, problems, query, savedItem, setQuery, siteValue, stories }: {
  changeState: FileState; disabled: boolean; drawn: CheckRow[] | null; editable: boolean; field: FieldFile | undefined; isOpen: boolean; item: Folder; locked: boolean; lockedForSections: boolean;
  onReject: () => void; onRemove: () => void; onToggle: () => void; onUpdate: (text: string) => void; problems: string[]; query: string; savedItem: Folder | null; setQuery: (query: string) => void;
  siteValue: string; stories: PublishedStory[] | null;
}) {
  const severity = severityOf(item), SeverityIcon = SEVERITY_ICON[severity], StateIcon = STATE_ICON[changeState];
  const meta = (patch: Record<string, Scalar | Scalar[] | undefined>) => onUpdate(withMeta(item, patch));
  const list = (key: string) => (
    <Labelled field={key} hint="One per line." label={{ avoid: "Words and phrases to avoid", prefer: "Words and phrases to prefer", pattern: "Patterns to find (regular expressions)" }[key] ?? key}>
      <LineBox disabled={disabled} onLines={(next) => meta({ [key]: next })} value={linesOf(item, key)} />
    </Labelled>
  );
  return (
    <li className="vs-tile bg-background p-3 space-y-2" data-file-state={changeState} data-guideline-file={item.folder}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="space-y-1">
          <strong className="text-sm">{field?.label ?? item.folder}</strong> <span className="text-xs text-muted-foreground">{item.folder}/{FILE_NAME}</span>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Pill data-file-severity={severity}><SeverityIcon aria-hidden className="size-3" /> Severity: {SEVERITY_WORDS[severity]}</Pill>
            <Pill data-file-role={item.role}><FileText aria-hidden className="size-3" /> {item.role === "field" ? "Field file" : "Rule file"}</Pill>
            <Pill data-file-change={changeState}><StateIcon aria-hidden className="size-3" /> {STATE_WORDS[changeState]}</Pill>
            {locked ? <Pill data-file-locked><Lock aria-hidden className="size-3" /> Locked by site</Pill> : null}
            {lockedForSections ? <Pill data-file-locked-for-sections><Lock aria-hidden className="size-3" /> Locked: sections cannot change it</Pill> : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {changeState !== "unchanged" && editable ? <Button aria-label={`Reject the ${changeState === "removed" ? "removal" : "changes"} to ${item.folder}`} data-reject-file onClick={onReject} size="sm" type="button" variant="secondary"><X aria-hidden /> Reject</Button> : null}
          {editable && changeState !== "removed" ? <Button aria-label={`Remove ${item.folder}`} data-remove-file onClick={onRemove} size="sm" type="button" variant="ghost"><Trash2 aria-hidden /> Remove</Button> : null}
          {changeState !== "removed" ? <Button aria-expanded={isOpen} aria-label={`${isOpen ? "Close" : "Open"} ${item.folder}`} data-toggle-file onClick={onToggle} size="sm" type="button" variant="secondary">{isOpen ? <ChevronUp aria-hidden /> : <ChevronDown aria-hidden />}{isOpen ? "Close" : "Open"}</Button> : null}
        </div>
      </div>
      {changeState === "removed" ? <p className="flex items-center gap-2 text-sm" data-file-removed><FileX aria-hidden className="size-4" /> Removed. The file is deleted when you accept and save.</p> : <p className="text-sm text-muted-foreground" data-check-line>{checkLine(item, savedItem, drawn)}</p>}
      {problems.map((problem) => <p className="flex items-start gap-2 text-sm" data-file-problem key={problem} role="alert"><CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" /> <span><strong>Problem:</strong> {problem}</span></p>)}
      {isOpen ? (
        <div className="space-y-3" data-file-editor>
          {item.unreadable ? (
            <>
              <p className="flex items-start gap-2 text-sm" role="alert"><CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" /> <span><strong>Problem:</strong> The front matter cannot be read here: {item.unreadable} Correct the whole file below.</span></p>
              <Labelled field="file" label="The whole file"><textarea className={`${FIELD} font-mono`} disabled={disabled} onChange={(event) => onUpdate(event.target.value)} rows={12} value={item.text} /></Labelled>
            </>
          ) : (
            <>
              <Labelled field="description" label="Description"><input className={FIELD} disabled={disabled} onChange={(event) => meta({ description: event.target.value })} value={textOf(item, "description")} /></Labelled>
              {item.role === "rule" ? (
                <div className="space-y-1" data-field="severity">
                  <p className="text-sm font-medium">Severity</p>
                  <div className="flex flex-wrap gap-2">
                    {SEVERITIES.map((choice) => { const Icon = SEVERITY_ICON[choice]; return (
                      <Button aria-pressed={severity === choice} data-severity={choice} disabled={disabled} key={choice} onClick={() => meta({ severity: choice })} size="sm" type="button" variant={severity === choice ? "default" : "secondary"}><Icon aria-hidden /> {SEVERITY_WORDS[choice]}{severity === choice ? <span className="sr-only"> (selected)</span> : null}</Button>
                    ); })}
                  </div>
                  <p className="text-xs text-muted-foreground">{SEVERITY_HINTS[severity]}</p>
                </div>
              ) : <p className="text-xs text-muted-foreground" data-field="severity">Severity: Guidance. A field file is always guidance.</p>}
              {item.role === "rule" ? <>{list("avoid")}{list("prefer")}{list("pattern")}
                <Labelled field="maxLength" hint="The most characters a text may have. Leave empty for no limit." label="Longest text">
                  <input className={FIELD} disabled={disabled} inputMode="numeric" onChange={(event) => { const typed = event.target.value.trim(); if (typed === "") meta({ maxLength: undefined }); else if (/^\d+$/.test(typed)) meta({ maxLength: Number(typed) }); }} value={maxLengthOf(item)} />
                </Labelled></> : null}
              {siteValue ? <p className="text-xs text-muted-foreground" data-site-value>Site: {siteValue}</p> : null}
              {item.folder === "constraints" ? <p className="text-xs text-muted-foreground">Binding rules always apply to every section.</p> : null}
              {item.folder === "exemplars" ? <ExemplarPicker body={item.body} disabled={disabled} editable={editable} onBody={(body) => onUpdate(withBody(item, body))} query={query} setQuery={setQuery} stories={stories} /> : null}
              <Labelled field="body" hint={item.role === "field" ? { text: "The text itself.", bullets: "One sentence per line, each starting with '- '. A longer sentence continues on lines indented by two spaces.", json: "One fenced json block." }[field?.form ?? "text"] : "The prose of the guideline, in your own words."} label="Body">
                <textarea className={`${FIELD} ${field?.form === "json" ? "font-mono" : ""}`} disabled={disabled} onChange={(event) => onUpdate(withBody(item, event.target.value))} rows={field?.form === "json" ? 8 : 6} value={item.body} />
              </Labelled>
              {item.extras.length ? <p className="text-xs text-muted-foreground">Also holds {item.extras.join(", ")}, kept as they are.</p> : null}
            </>
          )}
        </div>
      ) : null}
    </li>
  );
}

function ExemplarPicker({ body, disabled, editable, onBody, query, setQuery, stories }: {
  body: string; disabled: boolean; editable: boolean; onBody: (body: string) => void; query: string; setQuery: (query: string) => void; stories: PublishedStory[] | null;
}) {
  const rows = exemplarsOf(body);
  if (rows === null) return <p className="text-xs text-muted-foreground" data-exemplars-unreadable>The examples are not a list yet, so Stories cannot be picked here. Write the list in the body.</p>;
  const matches = stories ? matchStories(stories, query) : [];
  const picked = (story: PublishedStory) => rows.some((row) => row.storyLineageId === story.lineageId);
  return (
    <div className="space-y-2" data-field="exemplars">
      <p className="text-sm font-medium">Voice examples</p>
      <p className="text-xs text-muted-foreground">Published Stories that show the voice. Agents read these as examples.</p>
      {rows.length === 0 ? <p className="text-sm text-muted-foreground">No examples picked yet.</p> : null}
      <ul className="space-y-2">
        {rows.map((row, index) => (
          <li className="vs-tile bg-muted/60 p-3 space-y-2" data-exemplar={row.storyLineageId} key={row.storyLineageId}>
            <div className="flex items-center justify-between gap-2"><strong className="text-sm">{storyTitle(stories ?? [], row.storyLineageId)}</strong>
              {editable ? <Button aria-label={`Remove example ${storyTitle(stories ?? [], row.storyLineageId)}`} onClick={() => onBody(exemplarsBody(rows.filter((_, at) => at !== index)))} size="icon" type="button" variant="ghost"><Trash2 aria-hidden /></Button> : null}</div>
            <input aria-label={`Why ${storyTitle(stories ?? [], row.storyLineageId)} is a good example`} className={FIELD} disabled={disabled} onChange={(event) => onBody(exemplarsBody(rows.map((item, at) => (at === index ? { storyLineageId: item.storyLineageId, ...(event.target.value ? { note: event.target.value } : {}) } : item))))} placeholder="What it shows about the voice" value={row.note ?? ""} />
          </li>
        ))}
      </ul>
      {editable ? (
        <div className="space-y-2" data-story-picker>
          <label className="flex items-center gap-2 text-sm font-medium"><Search aria-hidden className="size-4" /> Find a published Story
            <input className={FIELD} onChange={(event) => setQuery(event.target.value)} placeholder="Part of the title" value={query} />
          </label>
          {stories === null ? <p className="text-sm text-muted-foreground" role="status">Loading published Stories…</p> : matches.length === 0 ? <p className="text-sm text-muted-foreground">No published Story matches.</p> : (
            <ul className="space-y-1">{matches.map((story) => (
              <li className="flex items-center justify-between gap-2 vs-tile bg-muted/60 px-3 py-2 text-sm" data-story-option={story.lineageId} key={story.lineageId}>
                <span>{story.title}</span>
                <Button disabled={disabled || picked(story)} onClick={() => onBody(exemplarsBody([...rows, { storyLineageId: story.lineageId }]))} size="sm" type="button" variant="secondary"><Plus aria-hidden /> {picked(story) ? "Picked" : "Use as example"}</Button>
              </li>))}</ul>
          )}
        </div>
      ) : null}
    </div>
  );
}

// --- what is in effect ------------------------------------------------------------------------------------------------------------------------------

function EffectivePage({ own, resolved, sectionName, siteDocument }: { own: Loaded; resolved: { document: GuidelineDocument; fieldSources: FieldSources } | null; sectionName: string; siteDocument: GuidelineDocument | null }) {
  if (!resolved) return <p className="text-sm text-muted-foreground" role="status">The guidelines in effect could not be worked out.</p>;
  const fields = Object.keys(resolved.document).filter((key) => key !== "schemaVersion" && key !== "locked");
  return (
    <div className={`${PANEL} space-y-3`} data-writing-guidelines-page-body="effective">
      <p className="text-sm">What an agent writing for <strong>{sectionName}</strong> reads: the site&apos;s guidelines with this section&apos;s additions laid over them. {own.status !== "ready" ? "This section has no additions yet, so every field comes from the site." : ""}</p>
      <ul className="space-y-2">
        {fields.map((field) => (
          <li className="vs-tile bg-background p-3 space-y-1" data-effective-field={field} key={field}>
            <div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-sm">{FIELD_LABELS[field] ?? field}</strong><SourceTag field={field} words={sourceWords(field, resolved.fieldSources, siteDocument, true)} /></div>
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">{valueWords(resolved.document[field])}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- history ----------------------------------------------------------------------------------------------------------------------------------------

function HistoryPage({ door, section }: { door: GuidelinesDoor; section: string | null }) {
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const [lines, setLines] = useState<string[] | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const answer = await door("guidelines_history", { kind: "writing", ...(section ? { section } : {}) });
        if (!live) return;
        if (answer.ok) setVersions(answer.result.versions as Version[]); else if (answer.error.code === "not_found") setVersions([]); else setProblem(answer.error.message);
      } catch (error) { if (live) setProblem(error instanceof Error ? error.message : "Could not load the history."); }
    })();
    return () => { live = false; };
  }, [door, section]);

  const toggle = (number: number) => { setLines(null); setPicked((current) => (current.includes(number) ? current.filter((item) => item !== number) : [...current, number].slice(-2))); };
  const compare = async () => {
    const [older, newer] = [...picked].sort((a, b) => a - b);
    const [first, second] = await Promise.all([older, newer].map((version) => door("guidelines_get", { kind: "writing", ...(section ? { section } : {}), version })));
    if (!first.ok || !second.ok) { setProblem("One of those versions could not be read."); return; }
    setLines([...diffDocuments(first.result.document, second.result.document).map(describeChange),
      ...ruleFileChanges(filesFrom(first.result.files), filesFrom(second.result.files)).map((change) => `Rule file ${change.folder}: ${change.change}`)]);
  };

  if (problem) return <p className="flex items-center gap-2" role="alert"><CircleAlert aria-hidden className="size-4" /> <strong>Problem:</strong> {problem}</p>;
  if (!versions) return <p className="flex items-center gap-2" role="status"><Loader aria-hidden className="size-4 animate-spin" /> Loading the history…</p>;
  if (!versions.length) return <p className="text-sm text-muted-foreground" data-writing-guidelines-page-body="history">No versions yet.</p>;
  return (
    <div className={`${PANEL} space-y-3`} data-writing-guidelines-page-body="history">
      <p className="text-sm">Every save is a version, with who made it and why. Pick two to see what changed between them.</p>
      <ul className="space-y-2">
        {versions.map((version) => {
          const on = picked.includes(version.versionNumber);
          return (
            <li className="vs-tile bg-background p-3" data-version={version.versionNumber} key={version.itemId}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <strong className="text-sm">Version {version.versionNumber}{version.isCurrent ? " (current)" : ""}</strong>
                <Button aria-pressed={on} onClick={() => toggle(version.versionNumber)} size="sm" type="button" variant={on ? "default" : "secondary"}>{on ? "Picked for comparison" : "Pick to compare"}</Button>
              </div>
              <p className="text-sm text-muted-foreground">{version.by || "Someone"}{version.byKind === "agent" ? " (agent)" : ""}, {version.at ? new Date(version.at).toLocaleString() : "at an unknown time"}</p>
              <p className="text-sm">Why: {version.reason || "No reason recorded."}</p>
            </li>
          );
        })}
      </ul>
      <Button data-compare disabled={picked.length !== 2} onClick={() => void compare()} type="button" variant="secondary"><History aria-hidden /> Compare the two picked versions</Button>
      {picked.length !== 2 ? <p className="text-xs text-muted-foreground">Pick exactly two versions.</p> : null}
      {lines ? (
        <div data-version-diff><p className="text-sm font-medium">{lines.length ? "Between those versions:" : "Those versions say the same thing."}</p><ul className="list-disc pl-5 text-sm">{lines.map((line) => <li key={line}>{line}</li>)}</ul></div>
      ) : null}
    </div>
  );
}

// --- the checks drawn from these guidelines ---------------------------------------------------------------------------------------------------------

async function realChecks(): Promise<CheckRow[]> {
  return (await listPolicies()).map((policy) => ({ id: policy.id, title: policy.title, enabled: policy.enabled, source: policy.source, policyKey: policy.policyKey }));
}

function ChecksList({ checksHref, rows }: { checksHref: string; rows: CheckRow[] | null }) {
  const shown = useMemo(() => rows ?? [], [rows]);
  return (
    <div className={`${PANEL} space-y-2`} data-derived-checks>
      <h4 className="flex items-center gap-2 font-semibold"><ListChecks aria-hidden className="size-4" /> Checks drawn from these guidelines</h4>
      <p className="text-xs text-muted-foreground">Saving keeps these editorial checks in step with the guidelines: each error or warning rule file derives one. A check you write or edit yourself is never changed by a save.</p>
      {rows === null ? <p className="text-sm text-muted-foreground" role="status">Loading the checks…</p> : shown.length === 0 ? <p className="text-sm text-muted-foreground">No checks are drawn from these guidelines yet.</p> : (
        <ul className="space-y-1">{shown.map((row) => <li className="vs-tile bg-background px-3 py-2 text-sm" data-derived-check={row.id} key={row.id}>{row.title} <span className="text-muted-foreground">({row.enabled ? "on" : "off"})</span></li>)}</ul>
      )}
      <a className="inline-flex items-center gap-1 text-sm underline" data-checks-link href={checksHref}><LinkIcon aria-hidden className="size-4" /> Open Editorial checks</a>
    </div>
  );
}
