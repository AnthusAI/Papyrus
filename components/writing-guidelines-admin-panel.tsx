"use client";

/**
 * Administration > Policies > Writing guidelines: the publication's house voice as data, beside Visual style. A Site tab and one tab per section; a section tab
 * shows the effective guidelines with a word on every field for where it came from (Site, This section, Locked by site). Every read and write goes through the
 * guidelines door's operations; nothing here knows how a document is stored. Flat backgrounds and rounded shapes only, Lucide icons only, and every state is an
 * icon plus a word. Design: docs/plans/guidelines-as-data.md section 8.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleAlert, CircleCheck, FilePenLine, History, Info, Layers, Link as LinkIcon, ListChecks, Loader, Lock, PenLine, Plus, Save, Search, Trash2, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { listPolicies } from "../lib/editorial-checks-client";
import { guidelinesDoor, listPublishedStories } from "../lib/guidelines/guidelines-door-client";
import {
  CHOICE_FIELDS, EDITORS_READ_ONLY, FIELD_LABELS, LIST_FIELDS, LOCKABLE_FIELDS, NO_WRITING_WARNING, SITE_TAB, addExemplar, derivedChecks, describeChange, diffDocuments,
  documentFromForm, formFromDocument, isLocked, matchStories, reasonProblem, sourceWords, storyTitle, valueWords,
  type FieldSources, type GuidelineDocument, type GuidelinesDoor, type ListPublishedStories, type PublishedStory, type WritingForm,
} from "../lib/guidelines/writing-guidelines-admin";

export type GuidelineSection = { key: string; name: string };
type Version = { itemId: string; versionNumber: number; isCurrent?: boolean; at?: string; by?: string; byKind?: string; reason?: string };
type Loaded = { status: "loading" } | { status: "error"; message: string } | { status: "none"; guard: string }
  | { status: "ready"; document: GuidelineDocument; guard: string; versionNumber: number; updatedBy: string; updatedAt: string };
type Note = { tone: "ok" | "error" | "info"; text: string };
type Page = "edit" | "effective" | "history";
type CheckRow = { id: string; title: string; enabled: boolean; source: string };

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

export function WritingGuidelinesAdmin({ door = guidelinesDoor, listStories = listPublishedStories, listChecks, sections = [], isAdmin = false, checksHref = "/newsroom/administration/editorial-checks" }: {
  door?: GuidelinesDoor; listStories?: ListPublishedStories; listChecks?: () => Promise<CheckRow[]>; sections?: GuidelineSection[]; isAdmin?: boolean; checksHref?: string;
}) {
  const [tab, setTab] = useState<string>(SITE_TAB);
  const [page, setPage] = useState<Page>("edit");
  const [site, setSite] = useState<Loaded>({ status: "loading" });
  const [own, setOwn] = useState<Loaded>({ status: "loading" });
  const [resolved, setResolved] = useState<{ document: GuidelineDocument; fieldSources: FieldSources } | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const section = tab === SITE_TAB ? null : tab;
  const sectionName = sections.find((item) => item.key === tab)?.name ?? tab;

  const read = useCallback(async (sectionKey: string | null): Promise<Loaded> => {
    try {
      const answer = await door("guidelines_get", { kind: "writing", ...(sectionKey ? { section: sectionKey } : {}) });
      if (answer.ok) {
        const result = answer.result;
        return { status: "ready", document: result.document, guard: result.expectedCurrentVersionId, versionNumber: result.versionNumber, updatedBy: result.updatedBy ?? "", updatedAt: result.updatedAt ?? "" };
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
        <EditPage door={door} isAdmin={isAdmin} key={tab} listStories={listStories} loaded={own} onSaved={async (text) => { await load(); setNote({ tone: "ok", text }); }} section={section} setNote={setNote} siteDocument={siteDocument} sectionName={sectionName} />
      ) : null}
      {page === "effective" && section ? <EffectivePage own={own} resolved={resolved} sectionName={sectionName} siteDocument={siteDocument} /> : null}
      {page === "history" ? <HistoryPage door={door} section={section} /> : null}
      <ChecksList checksHref={checksHref} listChecks={listChecks} section={section} versionKey={own.status === "ready" ? own.versionNumber : 0} />
    </section>
  );
}

// --- editing ----------------------------------------------------------------------------------------------------------------------------------------

function TextArea({ label, hint, value, onChange, disabled, field, rows = 3, locked }: { label: string; hint?: string; value: string; onChange: (value: string) => void; disabled: boolean; field: string; rows?: number; locked?: boolean }) {
  return (
    <label className="block space-y-1" data-field={field}>
      <span className="flex flex-wrap items-center gap-2 text-sm font-medium">{label}{locked ? <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Lock aria-hidden className="size-3" /> Locked by site</span> : null}</span>
      {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      <textarea className={FIELD} disabled={disabled} onChange={(event) => onChange(event.target.value)} rows={rows} value={value} />
    </label>
  );
}

function EditPage({ door, isAdmin, listStories, loaded, onSaved, section, sectionName, setNote, siteDocument }: {
  door: GuidelinesDoor; isAdmin: boolean; listStories: ListPublishedStories; loaded: Loaded; onSaved: (text: string) => Promise<void>; section: string | null; sectionName: string;
  setNote: (note: Note | null) => void; siteDocument: GuidelineDocument | null;
}) {
  const base = loaded.status === "ready" ? loaded.document : null;
  const [form, setForm] = useState<WritingForm>(() => formFromDocument(base));
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [stories, setStories] = useState<PublishedStory[] | null>(null);
  const [query, setQuery] = useState("");
  const versionKey = loaded.status === "ready" ? loaded.versionNumber : loaded.status;
  useEffect(() => { setForm(formFromDocument(base)); setReason(""); setPreview(null); }, [versionKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (isAdmin) void listStories().then(setStories).catch(() => setStories([])); }, [isAdmin, listStories]);

  const locked = (field: string) => section !== null && isLocked(siteDocument, field);
  const disabled = !isAdmin || busy;
  const scope = section ? "section" : "publication";
  const guard = loaded.status === "ready" || loaded.status === "none" ? loaded.guard : "none";
  const set = (patch: Partial<WritingForm>) => { setForm((current) => ({ ...current, ...patch })); setPreview(null); };

  const draft = () => documentFromForm(form, base, scope);

  const showChanges = async () => {
    setBusy(true); setNote(null);
    try {
      const answer = await door("guidelines_diff", { kind: "writing", ...(section ? { section } : {}), document: draft() });
      if (!answer.ok) { setNote({ tone: "error", text: answer.error.message }); return; }
      setPreview(answer.result.changes.length ? answer.result.changes.map(describeChange) : []);
    } catch (error) { setNote({ tone: "error", text: error instanceof Error ? error.message : "Could not work out what would change." }); } finally { setBusy(false); }
  };

  const save = async () => {
    const problem = reasonProblem(reason);
    if (problem) { setNote({ tone: "error", text: problem }); return; }
    setBusy(true); setNote(null);
    try {
      const answer = await door("guidelines_save", { kind: "writing", ...(section ? { section } : {}), document: draft(), reason: reason.trim(), expectedCurrentVersionId: guard });
      if (!answer.ok) {
        setNote({ tone: "error", text: answer.error.code === "stale_version" ? "Someone else changed the guidelines while you were editing. They have been reloaded; make your change again." : answer.error.message });
        if (answer.error.code === "stale_version") await onSaved("The latest guidelines are loaded.");
        return;
      }
      await onSaved(answer.result.unchanged ? "Nothing changed, so no new version was made." : `Saved as version ${answer.result.versionNumber}.`);
    } catch (error) { setNote({ tone: "error", text: error instanceof Error ? error.message : "The guidelines could not be saved." }); } finally { setBusy(false); }
  };

  if (loaded.status === "loading") return <p className="flex items-center gap-2" role="status"><Loader aria-hidden className="size-4 animate-spin" /> Loading…</p>;
  if (loaded.status === "error") return <p className="flex items-center gap-2" role="alert"><CircleAlert aria-hidden className="size-4" /> <strong>Problem:</strong> {loaded.message}</p>;

  const matches = stories ? matchStories(stories, query) : [];
  return (
    <div className="space-y-4" data-writing-guidelines-page-body="edit">
      {section ? <p className="flex items-start gap-2 text-sm" data-section-explainer><Info aria-hidden className="mt-0.5 size-4 shrink-0" /> <span>These are the additions for <strong>{sectionName}</strong>. They are laid over the site&apos;s guidelines: prose and word lists add to the site&apos;s, and a choice replaces the site&apos;s unless the site locks it. See the In effect page for the result.</span></p> : null}
      {loaded.status === "none" ? <p className="text-sm text-muted-foreground" data-no-document>{section ? "This section has no additions yet, so it follows the site's guidelines." : "Nothing is saved yet. The first save makes version 1."}</p> : null}

      <div className={`${PANEL} space-y-4`}>
        <h4 className="font-semibold">Voice and audience</h4>
        <label className="block space-y-1" data-field="voice">
          <span className="flex flex-wrap items-center gap-2 text-sm font-medium">Voice name{locked("voice") ? <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Lock aria-hidden className="size-3" /> Locked by site</span> : null}</span>
          <input className={FIELD} disabled={disabled || locked("voice")} onChange={(event) => set({ voiceName: event.target.value })} placeholder={section ? asPlaceholder(siteDocument?.voice?.name) : ""} value={form.voiceName} />
        </label>
        {CHOICE_FIELDS.map((field) => (
          <TextArea disabled={disabled || locked(field.key)} field={field.key} hint={field.hint} key={field.key} label={field.label} locked={locked(field.key)} onChange={(value) => set({ [field.key]: value } as Partial<WritingForm>)} rows={2} value={form[field.key as "audience" | "editorialAim"]} />
        ))}
      </div>

      <div className={`${PANEL} space-y-4`}>
        <h4 className="font-semibold">How it sounds</h4>
        {LIST_FIELDS.map((field) => (
          <TextArea disabled={disabled} field={field.key} hint={field.hint} key={field.key} label={field.label} onChange={(value) => set({ lists: { ...form.lists, [field.key]: value } })} value={form.lists[field.key] ?? ""} />
        ))}
        <TextArea disabled={disabled} field="bodyMarkus" hint="Free guidance in Markus, for anything the fields above do not cover." label={FIELD_LABELS.bodyMarkus} onChange={(value) => set({ bodyMarkus: value })} rows={6} value={form.bodyMarkus} />
      </div>

      <div className={`${PANEL} space-y-4`}>
        <h4 className="font-semibold">Words</h4>
        <TextArea disabled={disabled} field="lexicon.prefer" hint="Words and phrases to use. One per line." label="Prefer" onChange={(value) => set({ prefer: value })} value={form.prefer} />
        <TextArea disabled={disabled} field="lexicon.avoid" hint="Words and phrases to avoid. One per line. A section can add to these, never remove one." label="Avoid" onChange={(value) => set({ avoid: value })} value={form.avoid} />
        <div className="space-y-2" data-field="glossary">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium">Glossary{locked("glossary") ? <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Lock aria-hidden className="size-3" /> Locked by site</span> : null}</p>
          <p className="text-xs text-muted-foreground">Current names for products and things, and the old names to avoid (separated by commas).</p>
          {form.glossary.map((row, index) => (
            <div className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]" data-glossary-row={index} key={index}>
              <input aria-label={`Term ${index + 1}`} className={FIELD} disabled={disabled || locked("glossary")} onChange={(event) => set({ glossary: form.glossary.map((item, at) => (at === index ? { ...item, term: event.target.value } : item)) })} placeholder="Term" value={row.term} />
              <input aria-label={`Use ${index + 1}`} className={FIELD} disabled={disabled || locked("glossary")} onChange={(event) => set({ glossary: form.glossary.map((item, at) => (at === index ? { ...item, use: event.target.value } : item)) })} placeholder="Use" value={row.use} />
              <input aria-label={`Avoid ${index + 1}`} className={FIELD} disabled={disabled || locked("glossary")} onChange={(event) => set({ glossary: form.glossary.map((item, at) => (at === index ? { ...item, avoid: event.target.value } : item)) })} placeholder="Avoid, separated by commas" value={row.avoid} />
              <Button aria-label={`Remove glossary term ${index + 1}`} disabled={disabled || locked("glossary")} onClick={() => set({ glossary: form.glossary.filter((_, at) => at !== index) })} size="icon" type="button" variant="ghost"><Trash2 aria-hidden /></Button>
            </div>
          ))}
          {isAdmin && !locked("glossary") ? <Button data-add-glossary onClick={() => set({ glossary: [...form.glossary, { term: "", use: "", avoid: "" }] })} size="sm" type="button" variant="secondary"><Plus aria-hidden /> Add a term</Button> : null}
        </div>
      </div>

      <div className={`${PANEL} space-y-3`} data-field="exemplars">
        <h4 className="font-semibold">Voice examples</h4>
        <p className="text-xs text-muted-foreground">Published Stories that show the voice. Agents read these as examples. Pick them from the Stories this publication has published.</p>
        {form.exemplars.length === 0 ? <p className="text-sm text-muted-foreground">No examples picked yet.</p> : null}
        <ul className="space-y-2">
          {form.exemplars.map((row, index) => (
            <li className="vs-tile bg-background p-3 space-y-2" data-exemplar={row.storyLineageId} key={row.storyLineageId}>
              <div className="flex items-center justify-between gap-2"><strong className="text-sm">{storyTitle(stories ?? [], row.storyLineageId)}</strong>
                {isAdmin ? <Button aria-label={`Remove example ${storyTitle(stories ?? [], row.storyLineageId)}`} onClick={() => set({ exemplars: form.exemplars.filter((_, at) => at !== index) })} size="icon" type="button" variant="ghost"><Trash2 aria-hidden /></Button> : null}</div>
              <input aria-label={`Why ${storyTitle(stories ?? [], row.storyLineageId)} is a good example`} className={FIELD} disabled={disabled} onChange={(event) => set({ exemplars: form.exemplars.map((item, at) => (at === index ? { ...item, note: event.target.value } : item)) })} placeholder="What it shows about the voice" value={row.note} />
            </li>
          ))}
        </ul>
        {isAdmin ? (
          <div className="space-y-2" data-story-picker>
            <label className="flex items-center gap-2 text-sm font-medium"><Search aria-hidden className="size-4" /> Find a published Story
              <input className={FIELD} onChange={(event) => setQuery(event.target.value)} placeholder="Part of the title" value={query} />
            </label>
            {stories === null ? <p className="text-sm text-muted-foreground" role="status">Loading published Stories…</p> : matches.length === 0 ? <p className="text-sm text-muted-foreground">No published Story matches.</p> : (
              <ul className="space-y-1">{matches.map((story) => (
                <li className="flex items-center justify-between gap-2 vs-tile bg-background px-3 py-2 text-sm" data-story-option={story.lineageId} key={story.lineageId}>
                  <span>{story.title}</span>
                  <Button disabled={form.exemplars.some((row) => row.storyLineageId === story.lineageId)} onClick={() => set({ exemplars: addExemplar(form.exemplars, story) })} size="sm" type="button" variant="secondary"><Plus aria-hidden /> {form.exemplars.some((row) => row.storyLineageId === story.lineageId) ? "Picked" : "Use as example"}</Button>
                </li>))}</ul>
            )}
          </div>
        ) : null}
      </div>

      {!section ? (
        <div className={`${PANEL} space-y-3`} data-field="locked">
          <h4 className="flex items-center gap-2 font-semibold"><Lock aria-hidden className="size-4" /> Fields sections cannot change</h4>
          <p className="text-xs text-muted-foreground">A locked field is the site&apos;s alone: a section tab shows it as &quot;Locked by site&quot; and cannot replace it.</p>
          <div className="flex flex-wrap gap-2">
            {LOCKABLE_FIELDS.map((field) => {
              const on = form.locked.includes(field.key);
              return (
                <Button aria-pressed={on} data-lock-field={field.key} disabled={disabled} key={field.key} onClick={() => set({ locked: on ? form.locked.filter((item) => item !== field.key) : [...form.locked, field.key] })} size="sm" type="button" variant={on ? "default" : "secondary"}>
                  {on ? <Lock aria-hidden /> : <Layers aria-hidden />}{field.label}: {on ? "locked" : "open"}
                </Button>
              );
            })}
          </div>
          {Array.isArray(base?.constraints) && base!.constraints.length ? (
            <div data-binding-rules><h5 className="mt-2 text-sm font-medium">Binding rules</h5><p className="text-xs text-muted-foreground">Only an admin who is a person can change these, with the command line. They always apply to every section.</p>
              <ul className="mt-1 list-disc pl-5 text-sm">{base!.constraints.map((item: any) => <li key={item.id}>{item.text}</li>)}</ul></div>
          ) : null}
        </div>
      ) : null}

      {isAdmin ? (
        <div className={`${PANEL} space-y-3`} data-save-bar>
          <label className="block space-y-1"><span className="text-sm font-medium">Why are you changing the guidelines? (required)</span>
            <input className={FIELD} data-save-reason onChange={(event) => setReason(event.target.value)} placeholder="For example: tighten the tone after the style review" value={reason} />
          </label>
          {preview ? (
            <div data-change-preview>
              <p className="text-sm font-medium">{preview.length ? `Saving would change ${preview.length} ${preview.length === 1 ? "field" : "fields"}:` : "Nothing would change."}</p>
              <ul className="list-disc pl-5 text-sm">{preview.map((line) => <li key={line}>{line}</li>)}</ul>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button data-show-changes disabled={busy} onClick={() => void showChanges()} type="button" variant="secondary"><Eye aria-hidden /> Show what would change</Button>
            <Button data-save disabled={busy || reasonProblem(reason) !== null} onClick={() => void save()} type="button"><Save aria-hidden /> Save as a new version</Button>
          </div>
          {reasonProblem(reason) ? <p className="flex items-center gap-2 text-sm text-muted-foreground" data-reason-needed><Info aria-hidden className="size-4" /> Saving is possible once you give a reason.</p> : null}
        </div>
      ) : null}
    </div>
  );
}

const asPlaceholder = (value: unknown): string => (typeof value === "string" && value ? `Site: ${value}` : "");

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
    setLines(diffDocuments(first.result.document, second.result.document).map(describeChange));
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
  return (await listPolicies()).map((policy) => ({ id: policy.id, title: policy.title, enabled: policy.enabled, source: policy.source }));
}

function ChecksList({ checksHref, listChecks = realChecks, section, versionKey }: { checksHref: string; listChecks?: () => Promise<CheckRow[]>; section: string | null; versionKey: number }) {
  const [rows, setRows] = useState<CheckRow[] | null>(null);
  useEffect(() => { let live = true; void listChecks().then((all) => { if (live) setRows(derivedChecks(all, section)); }).catch(() => { if (live) setRows([]); }); return () => { live = false; }; }, [listChecks, section, versionKey]);
  const shown = useMemo(() => rows ?? [], [rows]);
  return (
    <div className={`${PANEL} space-y-2`} data-derived-checks>
      <h4 className="flex items-center gap-2 font-semibold"><ListChecks aria-hidden className="size-4" /> Checks drawn from these guidelines</h4>
      <p className="text-xs text-muted-foreground">Saving keeps these editorial checks in step with the guidelines. A check you write or edit yourself is never changed by a save.</p>
      {rows === null ? <p className="text-sm text-muted-foreground" role="status">Loading the checks…</p> : shown.length === 0 ? <p className="text-sm text-muted-foreground">No checks are drawn from these guidelines yet.</p> : (
        <ul className="space-y-1">{shown.map((row) => <li className="vs-tile bg-background px-3 py-2 text-sm" data-derived-check={row.id} key={row.id}>{row.title} <span className="text-muted-foreground">({row.enabled ? "on" : "off"})</span></li>)}</ul>
      )}
      <a className="inline-flex items-center gap-1 text-sm underline" data-checks-link href={checksHref}><LinkIcon aria-hidden className="size-4" /> Open Editorial checks</a>
    </div>
  );
}
