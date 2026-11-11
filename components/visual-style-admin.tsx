"use client";

/**
 * Administration > Policies > Visual style: the publication's image style, in plain words. Brand (identity and the review setting), Image types (a list, a page
 * for each) and, for each type, its example pictures. Every read and write goes through the image-service door's operations; nothing here knows how a profile is
 * stored. Flat backgrounds and vs-small shapes only, Lucide icons only, and every state is an icon plus a word. Design: project/wiki/image-toolchain.md section 8.
 */
/* eslint-disable @next/next/no-img-element -- example pictures are short-lived signed addresses, not site assets */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Archive, ArchiveRestore, ArrowDown, ArrowLeft, ArrowUp, Ban, Check, CircleAlert, CircleCheck, Eye, Images, Info, Layers, Lock, Palette, Plus, ImagePlus, Save, Send,
  CircleOff, FilePenLine, Sparkles, PenTool, ThumbsUp, Trash2, Loader, CornerDownRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { exampleUrl as realExampleUrl, imageDoor, uploadExample as realUploadExample, type ExampleUrl, type ImageDoor, type UploadExample } from "../lib/images/image-door-client";
import {
  IDENTITY_SCOPE, NO_STYLE_WARNING, REVIEW_CHOICES, SOURCE_LABELS, USE_LABELS, addTypeDocument, effectiveUse, effectiveView, examplesFor, imageTypeRows, moveSource,
  pictureProblem, ratioOf, retireDocument, safeZoneBox, textLines, typeDefinitions, unusedSources, type Example, type ImageTypeRow, type Profile, type Source,
} from "../lib/images/visual-style-admin";

type Loaded = { status: "loading" } | { status: "error"; message: string } | { status: "none" }
  | { status: "ready"; profile: Profile; itemId: string; versionNumber: number; updatedBy: string; updatedAt: string };
type View = { name: "brand" } | { name: "types" } | { name: "type"; key: string };
type Note = { tone: "ok" | "error" | "info"; text: string };

const FIELD = "w-full vs-tile bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring";
const PANEL = "vs-panel bg-muted/60 p-4";

const SOURCE_ICONS: Record<Source, ReactNode> = { "figure-system": <PenTool aria-hidden />, stock: <Images aria-hidden />, generated: <Sparkles aria-hidden /> };

function StatusLine({ note }: { note: Note | null }) {
  return (
    <div aria-live="polite" className="flex items-center gap-2 text-sm" data-visual-style-status role="status">
      {note ? (note.tone === "error" ? <CircleAlert aria-hidden className="size-4" /> : note.tone === "ok" ? <CircleCheck aria-hidden className="size-4" /> : <Info aria-hidden className="size-4" />) : null}
      {note ? <span><strong>{note.tone === "error" ? "Problem: " : note.tone === "ok" ? "Done: " : ""}</strong>{note.text}</span> : null}
    </div>
  );
}

function SourceChips({ sources }: { sources: Source[] }) {
  if (!sources.length) return <span className="text-sm text-muted-foreground">No sources set</span>;
  return (
    <ol className="flex flex-wrap items-center gap-1.5" data-visual-style-sources>
      {sources.map((source, index) => (
        <li className="inline-flex items-center gap-1.5 vs-pill bg-secondary px-2.5 py-1 text-xs font-medium text-secondary-foreground" key={source}>
          <span className="tabular-nums">{index + 1}.</span><span className="[&_svg]:size-3.5">{SOURCE_ICONS[source]}</span>{SOURCE_LABELS[source]?.label ?? source}
        </li>
      ))}
    </ol>
  );
}

export function VisualStyleAdmin({ door = imageDoor, uploadPicture = realUploadExample, pictureUrl = realExampleUrl, isAdmin = false }: {
  door?: ImageDoor; uploadPicture?: UploadExample; pictureUrl?: ExampleUrl; isAdmin?: boolean;
}) {
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });
  const [view, setView] = useState<View>({ name: "brand" });
  const [note, setNote] = useState<Note | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const answer = await door("image_profile_get", {});
      if (answer.ok) {
        const { profile, itemId, versionNumber, updatedBy, updatedAt } = answer.result;
        setLoaded({ status: "ready", profile: profile as Profile, itemId, versionNumber, updatedBy: updatedBy ?? "", updatedAt: updatedAt ?? "" });
      } else if (answer.error.code === "not_found") setLoaded({ status: "none" });
      else setLoaded({ status: "error", message: answer.error.message });
    } catch (error) {
      setLoaded({ status: "error", message: error instanceof Error ? error.message : "Could not load the visual style." });
    }
  }, [door]);
  useEffect(() => { void load(); }, [load]);

  const guard = loaded.status === "ready" ? loaded.itemId : "none";

  /** Save a partial document over the current profile and say what happened. Resolves true when it was saved. */
  const save = useCallback(async (document: Profile, reason: string, done: string): Promise<boolean> => {
    setBusy("save"); setNote(null);
    try {
      const answer = await door("image_profile_save", { document, reason, expectedCurrentVersionId: guard });
      if (!answer.ok) {
        setNote({ tone: "error", text: answer.error.code === "stale_version" ? "Someone else changed the style while you were editing. It has been reloaded; make your change again." : answer.error.message });
        if (answer.error.code === "stale_version") await load();
        return false;
      }
      await load();
      setNote({ tone: "ok", text: "unchanged" in answer.result ? "Nothing changed, so no new version was made." : `${done} (version ${answer.result.versionNumber}).` });
      return true;
    } catch (error) {
      setNote({ tone: "error", text: error instanceof Error ? error.message : "The change could not be saved." });
      return false;
    } finally { setBusy(null); }
  }, [door, guard, load]);

  if (loaded.status === "loading") return <p className="flex items-center gap-2" data-visual-style="loading" role="status"><Loader aria-hidden className="size-4 animate-spin" /> Loading the visual style…</p>;
  if (loaded.status === "error") return <p className="flex items-center gap-2" data-visual-style="error" role="alert"><CircleAlert aria-hidden className="size-4" /> <strong>Problem:</strong> {loaded.message}</p>;

  const profile = loaded.status === "ready" ? loaded.profile : null;
  const rows = imageTypeRows(profile);
  const openType = view.name === "type" ? rows.find((row) => row.key === view.key) ?? null : null;

  return (
    <section aria-labelledby="visual-style-title" className="space-y-5" data-news-desk-admin-panel="visual-style">
      <header className="space-y-1">
        <h3 className="flex items-center gap-2 text-lg font-semibold" id="visual-style-title"><Palette aria-hidden className="size-5" /> Visual style</h3>
        <p className="text-sm text-muted-foreground">
          How this publication&apos;s pictures should look, written once so editors and agents follow it. {loaded.status === "ready"
            ? `Version ${loaded.versionNumber}, last changed by ${loaded.updatedBy || "someone"}.` : "There is no style yet."}
        </p>
      </header>

      {loaded.status === "none" ? <NoStyle door={door} guard={guard} onSaved={async () => { await load(); setNote({ tone: "ok", text: "The first version of the style is saved." }); }} /> : null}

      {profile ? (
        <nav aria-label="Visual style sections" className="flex flex-wrap gap-2" data-visual-style-nav>
          <Button aria-pressed={view.name === "brand"} onClick={() => { setView({ name: "brand" }); setNote(null); }} type="button" variant={view.name === "brand" ? "default" : "secondary"}><Palette aria-hidden /> Brand{view.name === "brand" ? <span className="sr-only"> (selected)</span> : null}</Button>
          <Button aria-pressed={view.name !== "brand"} onClick={() => { setView({ name: "types" }); setNote(null); }} type="button" variant={view.name !== "brand" ? "default" : "secondary"}><Layers aria-hidden /> Image types ({rows.filter((row) => !row.retired).length}){view.name !== "brand" ? <span className="sr-only"> (selected)</span> : null}</Button>
        </nav>
      ) : null}
      <StatusLine note={note} />

      {profile && view.name === "brand" ? (
        <BrandPage busy={busy} door={door} isAdmin={isAdmin} onSave={save} pictureUrl={pictureUrl} profile={profile} setNote={setNote} uploadPicture={uploadPicture} guard={guard} reload={load} />
      ) : null}
      {profile && view.name === "types" ? <TypesPage busy={busy} onOpen={(key) => { setView({ name: "type", key }); setNote(null); }} onSave={save} profile={profile} rows={rows} /> : null}
      {profile && view.name === "type" && openType ? (
        <TypePage busy={busy} door={door} guard={guard} onBack={() => { setView({ name: "types" }); setNote(null); }} onSave={save} pictureUrl={pictureUrl} profile={profile} reload={load}
          row={openType} setNote={setNote} uploadPicture={uploadPicture} versionNumber={loaded.status === "ready" ? loaded.versionNumber : 0} />
      ) : null}
    </section>
  );
}

// --- no style yet -----------------------------------------------------------------------------------------------------------------------------------

function NoStyle({ door, guard, onSaved }: { door: ImageDoor; guard: string; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState<{ document: Profile; notes: string[]; expectedCurrentVersionId: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const makeDraft = async () => {
    setWorking(true); setProblem(null);
    const answer = await door("image_profile_init", {});
    setWorking(false);
    if (answer.ok) setDraft({ document: answer.result.document as Profile, notes: answer.result.notes, expectedCurrentVersionId: answer.result.expectedCurrentVersionId });
    else setProblem(answer.error.message);
  };
  const saveDraft = async () => {
    if (!draft) return;
    setWorking(true); setProblem(null);
    const answer = await door("image_profile_save", { document: draft.document, reason: "First profile, from the starting draft", expectedCurrentVersionId: draft.expectedCurrentVersionId || guard });
    setWorking(false);
    if (answer.ok) await onSaved(); else setProblem(answer.error.message);
  };
  const draftRows = draft ? imageTypeRows(draft.document) : [];
  return (
    <div className={PANEL} data-visual-style-warning="no-style" role="status">
      <p className="flex items-start gap-2 font-medium"><Info aria-hidden className="mt-0.5 size-4 shrink-0" /> <span><strong>No style yet.</strong> {NO_STYLE_WARNING}</span></p>
      <p className="mt-2 text-sm text-muted-foreground">Pictures can still be searched for and made without a style. They just will not follow any guidelines.</p>
      {!draft ? <Button className="mt-3" disabled={working} onClick={makeDraft} type="button">{working ? <Loader aria-hidden className="animate-spin" /> : <FilePenLine aria-hidden />} Draft a starting style</Button> : (
        <div className="mt-3 space-y-3" data-visual-style-draft>
          <p className="font-medium">A starting draft. It is not saved yet.</p>
          <ul className="space-y-1 text-sm">{draftRows.map((row) => <li key={row.key}><strong>{row.label}</strong>: {row.description}</li>)}</ul>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">{draft.notes.map((text) => <li key={text}>{text}</li>)}</ul>
          <div className="flex flex-wrap gap-2">
            <Button disabled={working} onClick={saveDraft} type="button"><Save aria-hidden /> Save this draft as the first version</Button>
            <Button onClick={() => setDraft(null)} type="button" variant="ghost"><Trash2 aria-hidden /> Discard the draft</Button>
          </div>
        </div>
      )}
      {problem ? <p className="mt-2 flex items-center gap-2 text-sm" role="alert"><CircleAlert aria-hidden className="size-4" /> <strong>Problem:</strong> {problem}</p> : null}
    </div>
  );
}

// --- brand ------------------------------------------------------------------------------------------------------------------------------------------

function LabelledArea({ label, hint, value, onChange, rows = 3 }: { label: string; hint?: string; value: string; onChange: (value: string) => void; rows?: number }) {
  const id = useMemo(() => `field-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`, [label]);
  return (
    <div className="space-y-1">
      <label className="text-sm font-medium" htmlFor={id}>{label}</label>
      {hint ? <p className="text-xs text-muted-foreground" id={`${id}-hint`}>{hint}</p> : null}
      <textarea aria-describedby={hint ? `${id}-hint` : undefined} className={FIELD} id={id} onChange={(event) => onChange(event.target.value)} rows={rows} value={value} />
    </div>
  );
}

function BrandPage({ profile, busy, onSave, isAdmin, door, guard, reload, setNote, uploadPicture, pictureUrl }: {
  profile: Profile; busy: string | null; onSave: (document: Profile, reason: string, done: string) => Promise<boolean>; isAdmin: boolean; door: ImageDoor; guard: string;
  reload: () => Promise<void>; setNote: (note: Note | null) => void; uploadPicture: UploadExample; pictureUrl: ExampleUrl;
}) {
  const identity = profile.identity ?? {};
  const [summary, setSummary] = useState<string>(identity.summary ?? "");
  const [masterPrompt, setMasterPrompt] = useState<string>(identity.masterPrompt ?? "");
  const [mood, setMood] = useState<string>((identity.mood ?? []).join(", "));
  const [palette, setPalette] = useState<{ name: string; hex: string; token?: string; role?: string }[]>(identity.palette ?? []);
  const [preferred, setPreferred] = useState<string>((profile.techniques?.preferred ?? []).join("\n"));
  const [avoided, setAvoided] = useState<string>((profile.techniques?.avoided ?? []).join("\n"));
  const [representation, setRepresentation] = useState<string>(profile.subjects?.representation ?? "");
  const [never, setNever] = useState<string>((profile.subjects?.never ?? []).join("\n"));
  const [reason, setReason] = useState("Edited the brand in Administration");
  const review = profile.imageReview ?? "before_publish";
  const limit: number | undefined = identity.paletteLimit;
  const changePalette = (index: number, patch: Partial<(typeof palette)[number]>) => setPalette((current) => current.map((entry, at) => (at === index ? { ...entry, ...patch } : entry)));
  const hexOk = (hex: string) => /^#[0-9a-fA-F]{6}$/.test(hex);
  const paletteProblem = palette.find((entry) => !entry.name.trim() || !hexOk(entry.hex)) ? "Every colour needs a name and a hex value like #1f2a44." : limit && palette.length > limit ? `The palette has ${palette.length} colours but the limit is ${limit}.` : null;

  return (
    <div className="space-y-5" data-visual-style-page="brand">
      <form className={`${PANEL} space-y-4`} data-visual-style-brand-form onSubmit={(event) => {
        event.preventDefault();
        if (paletteProblem) { setNote({ tone: "error", text: paletteProblem }); return; }
        void onSave({
          identity: { summary, masterPrompt, mood: mood.split(",").map((word) => word.trim()).filter(Boolean), palette },
          techniques: { preferred: textLines(preferred), avoided: textLines(avoided) }, subjects: { representation, never: textLines(never) },
        }, reason.trim() || "Edited the brand in Administration", "Brand saved");
      }}>
        <h4 className="font-semibold">Brand</h4>
        <LabelledArea hint="One or two plain sentences. Agents and editors see this first." label="Summary" onChange={setSummary} value={summary} />
        <LabelledArea hint="The sentence sent to the image model before anything else. Describe the look, not a subject." label="Master prompt" onChange={setMasterPrompt} value={masterPrompt} />
        <div className="space-y-1">
          <label className="text-sm font-medium" htmlFor="field-mood">Mood words (separated by commas)</label>
          <input className={FIELD} id="field-mood" onChange={(event) => setMood(event.target.value)} value={mood} />
        </div>
        <fieldset className="space-y-2" data-visual-style-palette>
          <legend className="text-sm font-medium">Palette{limit ? ` (up to ${limit} colours)` : ""}</legend>
          {palette.length === 0 ? <p className="text-sm text-muted-foreground">No colours yet.</p> : null}
          {palette.map((entry, index) => (
            <div className="grid grid-cols-[2.5rem_1fr_8rem_auto] items-center gap-2 max-sm:grid-cols-[2.5rem_1fr_auto]" data-palette-row key={index}>
              <span aria-hidden className="flex size-10 items-center justify-center vs-small bg-foreground/15"><span className="size-7 vs-small" style={{ background: hexOk(entry.hex) ? entry.hex : "transparent" }} /></span>
              <input aria-label={`Colour ${index + 1} name`} className={FIELD} onChange={(event) => changePalette(index, { name: event.target.value })} value={entry.name} />
              <input aria-label={`Colour ${index + 1} hex value`} className={`${FIELD} font-mono max-sm:col-span-2 max-sm:col-start-2`} onChange={(event) => changePalette(index, { hex: event.target.value })} value={entry.hex} />
              <Button aria-label={`Remove ${entry.name || "colour"}`} onClick={() => setPalette((current) => current.filter((_, at) => at !== index))} size="icon" type="button" variant="ghost"><Trash2 aria-hidden /></Button>
            </div>
          ))}
          <Button onClick={() => setPalette((current) => [...current, { name: "", hex: "#" }])} size="sm" type="button" variant="secondary"><Plus aria-hidden /> Add a colour</Button>
        </fieldset>
        <LabelledArea hint="One per line." label="Techniques to prefer" onChange={setPreferred} rows={2} value={preferred} />
        <LabelledArea hint="One per line. Never used anywhere in this publication." label="Techniques to avoid" onChange={setAvoided} rows={2} value={avoided} />
        <LabelledArea label="How people are shown" onChange={setRepresentation} rows={2} value={representation} />
        <LabelledArea hint="One per line. Never shown, in any image type." label="Never show" onChange={setNever} rows={2} value={never} />
        <div className="space-y-1">
          <label className="text-sm font-medium" htmlFor="field-reason">Why are you changing it?</label>
          <input className={FIELD} id="field-reason" onChange={(event) => setReason(event.target.value)} value={reason} />
        </div>
        <Button disabled={busy !== null} type="submit"><Save aria-hidden /> Save brand</Button>
      </form>

      <div className={`${PANEL} space-y-3`} data-visual-style-review>
        <h4 className="font-semibold">When pictures are reviewed</h4>
        <p className="text-sm text-muted-foreground">When an agent adds a picture without a person looking, should publishing wait for a review?</p>
        <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label="When pictures are reviewed">
          {REVIEW_CHOICES.map((choice) => {
            const selected = review === choice.value;
            return (
              <Button aria-pressed={selected} className="h-auto flex-col items-start gap-1 whitespace-normal p-3 text-left" data-review-choice={choice.value} disabled={busy !== null}
                key={choice.value} onClick={() => { if (!selected) void onSave({ imageReview: choice.value }, `Review ${choice.label.toLowerCase()}`, "Review setting saved"); }} type="button" variant={selected ? "default" : "secondary"}>
                <span className="flex items-center gap-2 font-semibold">{selected ? <Check aria-hidden /> : <Eye aria-hidden />} {choice.label}{selected ? " (selected)" : ""}</span>
                <span className="text-xs font-normal opacity-90">{choice.detail}</span>
              </Button>
            );
          })}
        </div>
      </div>

      <div className={`${PANEL} space-y-2`} data-visual-style-constraints>
        <h4 className="flex items-center gap-2 font-semibold"><Lock aria-hidden className="size-4" /> Binding rules</h4>
        {(profile.constraints ?? []).length === 0 ? <p className="text-sm text-muted-foreground">No binding rules. They stay off until an admin adds one.</p> : (
          <ul className="space-y-2">{(profile.constraints as Profile[]).map((rule) => (
            <li className="vs-tile bg-background p-3 text-sm" key={rule.id}><span className="font-medium">{rule.id}</span> <span className="text-muted-foreground">(version {rule.version ?? 1})</span><br />{rule.text}</li>
          ))}</ul>
        )}
        <p className="text-sm text-muted-foreground">{isAdmin ? "You are an admin, so you can change these with the command line: papyrus images profile save." : "Only an admin who is a person can add, change or remove a binding rule."} Agents cannot change them at all.</p>
      </div>

      <div className={`${PANEL} space-y-2`} data-visual-style-brand-examples>
        <h4 className="font-semibold">Pictures that show the whole brand</h4>
        <ExamplesGrid door={door} guard={guard} pictureUrl={pictureUrl} profile={profile} reload={reload} scope={IDENTITY_SCOPE} setNote={setNote} thumbnail={null} uploadPicture={uploadPicture} />
      </div>
    </div>
  );
}

// --- image types ------------------------------------------------------------------------------------------------------------------------------------

function TypesPage({ rows, onOpen, onSave, busy, profile }: { rows: ImageTypeRow[]; onOpen: (key: string) => void; onSave: (document: Profile, reason: string, done: string) => Promise<boolean>; busy: string | null; profile: Profile }) {
  const [adding, setAdding] = useState(false);
  const active = rows.filter((row) => !row.retired);
  const retired = rows.filter((row) => row.retired);
  return (
    <div className="space-y-4" data-visual-style-page="types">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">The kinds of picture this publication uses. A type&apos;s key can never change once it is saved; a type is retired instead.</p>
        <Button data-add-type onClick={() => setAdding(true)} type="button"><Plus aria-hidden /> Add a type</Button>
      </div>
      {adding ? <AddTypeForm busy={busy} onCancel={() => setAdding(false)} onSave={async (document, key) => { const saved = await onSave(document, `Added the ${key} image type`, "Image type added"); if (saved) { setAdding(false); onOpen(key); } return saved; }} profile={profile} rows={active} /> : null}
      {active.length === 0 ? <p className={PANEL}>No image types yet. Add one to say what kinds of picture this publication uses.</p> : null}
      <ul className="space-y-3">{active.map((row) => <TypeRow busy={busy} key={row.key} onOpen={onOpen} onSave={onSave} row={row} />)}</ul>
      {retired.length ? (
        <div className="space-y-2">
          <h4 className="flex items-center gap-2 text-sm font-semibold"><Archive aria-hidden className="size-4" /> Retired types</h4>
          <ul className="space-y-2">{retired.map((row) => <TypeRow busy={busy} key={row.key} onOpen={onOpen} onSave={onSave} row={row} />)}</ul>
        </div>
      ) : null}
    </div>
  );
}

function TypeRow({ row, onOpen, onSave, busy }: { row: ImageTypeRow; onOpen: (key: string) => void; onSave: (document: Profile, reason: string, done: string) => Promise<boolean>; busy: string | null }) {
  return (
    <li className={`${PANEL} space-y-2`} data-image-type-row={row.key} data-retired={row.retired || undefined}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="font-semibold">{row.label}{row.retired ? <span className="ml-2 inline-flex items-center gap-1 vs-pill bg-secondary px-2 py-0.5 text-xs font-medium"><Archive aria-hidden className="size-3" /> Retired</span> : null}</h4>
          <p className="text-sm text-muted-foreground">{row.description || "No description yet."}</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => onOpen(row.key)} size="sm" type="button" variant="secondary"><CornerDownRight aria-hidden /> Open</Button>
          <Button disabled={busy !== null} onClick={() => void onSave(retireDocument(row.key, !row.retired), row.retired ? `Brought back the ${row.key} image type` : `Retired the ${row.key} image type`, row.retired ? "Image type brought back" : "Image type retired")} size="sm" type="button" variant="ghost">
            {row.retired ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />} {row.retired ? "Bring back" : "Retire"}
          </Button>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-muted-foreground">Family</dt><dd>{row.family}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Used for</dt><dd>{row.useLabel}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Shown</dt><dd>{row.thumbnail === null ? "Not set" : row.thumbnail ? "As a thumbnail" : "Never as a thumbnail"}{row.smallestWidthPx ? `, as small as ${row.smallestWidthPx}px` : ""}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Examples</dt><dd>{row.exampleCount === 0 ? "None yet" : `${row.exampleCount} ${row.exampleCount === 1 ? "picture" : "pictures"}`}</dd></div>
      </dl>
      <div className="space-y-1"><span className="text-xs text-muted-foreground">Sources, best first</span><SourceChips sources={row.sources} /></div>
      {row.inheritsFrom ? <p className="text-xs text-muted-foreground">Starts from {row.inheritsFrom}. Its examples are its own: it does not inherit them.</p> : null}
    </li>
  );
}

function AddTypeForm({ profile, rows, busy, onCancel, onSave }: { profile: Profile; rows: ImageTypeRow[]; busy: string | null; onCancel: () => void; onSave: (document: Profile, key: string) => Promise<boolean> }) {
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [startFrom, setStartFrom] = useState<string | null>(null);
  const [use, setUse] = useState<"cover" | "inline" | "social">("cover");
  const [problem, setProblem] = useState<string | null>(null);
  const parentUse = startFrom ? (effectiveUse(profile, startFrom) as typeof use | null) : null;
  useEffect(() => { if (parentUse) setUse(parentUse); }, [parentUse]);
  return (
    <form className={`${PANEL} space-y-3`} data-add-type-form onSubmit={(event) => {
      event.preventDefault();
      const built = addTypeDocument(profile, { label, description, startFrom, use });
      if (built.problem || !built.document || !built.key) { setProblem(built.problem ?? "That type could not be added."); return; }
      setProblem(null);
      void onSave(built.document, built.key);
    }}>
      <h4 className="font-semibold">Add a type</h4>
      <div className="space-y-1"><label className="text-sm font-medium" htmlFor="new-type-name">Name</label><input className={FIELD} id="new-type-name" onChange={(event) => setLabel(event.target.value)} value={label} /></div>
      <div className="space-y-1"><label className="text-sm font-medium" htmlFor="new-type-description">One plain sentence about it</label><input className={FIELD} id="new-type-description" onChange={(event) => setDescription(event.target.value)} value={description} /></div>
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">Start from</legend>
        <p className="text-xs text-muted-foreground">It keeps everything the other type says, then adds its own rules. It does not copy that type&apos;s example pictures.</p>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Start from">
          <Button aria-pressed={startFrom === null} onClick={() => setStartFrom(null)} size="sm" type="button" variant={startFrom === null ? "default" : "secondary"}>{startFrom === null ? <Check aria-hidden /> : null} Nothing, start empty</Button>
          {rows.map((row) => (
            <Button aria-pressed={startFrom === row.key} key={row.key} onClick={() => setStartFrom(row.key)} size="sm" type="button" variant={startFrom === row.key ? "default" : "secondary"}>{startFrom === row.key ? <Check aria-hidden /> : null} {row.label}</Button>
          ))}
        </div>
      </fieldset>
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">Where it is used</legend>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Where it is used">
          {Object.entries(USE_LABELS).map(([value, name]) => (
            <Button aria-pressed={use === value} key={value} onClick={() => setUse(value as typeof use)} size="sm" type="button" variant={use === value ? "default" : "secondary"}>{use === value ? <Check aria-hidden /> : null} {name}</Button>
          ))}
        </div>
      </fieldset>
      {problem ? <p className="flex items-center gap-2 text-sm" role="alert"><CircleAlert aria-hidden className="size-4" /> <strong>Problem:</strong> {problem}</p> : null}
      <div className="flex gap-2"><Button disabled={busy !== null} type="submit"><Plus aria-hidden /> Add this type</Button><Button onClick={onCancel} type="button" variant="ghost">Cancel</Button></div>
    </form>
  );
}

// --- one type -------------------------------------------------------------------------------------------------------------------------------------

function TypePage({ profile, row, busy, onBack, onSave, door, guard, reload, setNote, uploadPicture, pictureUrl, versionNumber }: {
  profile: Profile; row: ImageTypeRow; busy: string | null; onBack: () => void; onSave: (document: Profile, reason: string, done: string) => Promise<boolean>; door: ImageDoor; guard: string;
  reload: () => Promise<void>; setNote: (note: Note | null) => void; uploadPicture: UploadExample; pictureUrl: ExampleUrl; versionNumber: number;
}) {
  const definition = typeDefinitions(profile)[row.key] ?? {};
  const [guidance, setGuidance] = useState<string>(definition.guidance ?? "");
  const [avoid, setAvoid] = useState<string>((definition.avoid ?? []).join("\n"));
  const sources: Source[] = definition.sources ?? row.sources;
  const ownSources = Boolean(definition.sources);
  const [effective, setEffective] = useState<{ status: "loading" } | { status: "none"; reason: string } | { status: "ready"; view: ReturnType<typeof effectiveView> }>({ status: "loading" });
  const use = effectiveUse(profile, row.key);

  useEffect(() => {
    let current = true;
    if (row.retired) { setEffective({ status: "none", reason: "A retired type is not resolved, so there are no effective rules to show. Bring it back to see them." }); return; }
    if (!use) { setEffective({ status: "none", reason: "Choose where this type is used to see its effective rules." }); return; }
    setEffective({ status: "loading" });
    void door("image_profile_resolve", { use: use as "cover", imageType: row.key }).then((answer) => {
      if (!current) return;
      setEffective(answer.ok ? { status: "ready", view: effectiveView(answer.result as Profile, profile, row.key) } : { status: "none", reason: answer.error.message });
    });
    return () => { current = false; };
  }, [door, profile, row.key, row.retired, use, versionNumber]);

  const zones: { region: string; instruction: string }[] = definition.safeZones ?? [];
  const frameRatio = ratioOf((definition.sizes ?? typeDefinitions(profile)[definition.extends ?? ""]?.sizes)?.aspectRatio);

  return (
    <div className="space-y-5" data-visual-style-page="type" data-image-type={row.key}>
      <Button onClick={onBack} size="sm" type="button" variant="ghost"><ArrowLeft aria-hidden /> All image types</Button>
      <header className="space-y-1">
        <h4 className="text-lg font-semibold">{row.label}{row.retired ? <span className="ml-2 inline-flex items-center gap-1 vs-pill bg-secondary px-2 py-0.5 text-xs font-medium"><Archive aria-hidden className="size-3" /> Retired</span> : null}</h4>
        <p className="text-sm text-muted-foreground">{row.description || "No description yet."} Key: <code>{row.key}</code> (permanent).{row.inheritsFrom ? ` Starts from ${row.inheritsFrom}.` : ""}</p>
      </header>

      <div className={`${PANEL} space-y-2`} data-visual-style-display>
        <h5 className="font-semibold">Where it appears</h5>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
          <div><dt className="text-xs text-muted-foreground">Used for</dt><dd>{row.useLabel}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Family</dt><dd>{row.family}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Shown</dt><dd>{row.thumbnail === null ? "Not set" : row.thumbnail ? "As a thumbnail" : "Never as a thumbnail"}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Smallest width</dt><dd>{row.smallestWidthPx ? `${row.smallestWidthPx}px` : "Not set"}</dd></div>
        </dl>
        {zones.length ? (
          <div className="space-y-2" data-safe-zones>
            <h6 className="text-sm font-medium">Safe zones</h6>
            <div className="relative w-full max-w-sm overflow-hidden vs-tile bg-background" style={{ aspectRatio: String(frameRatio) }} aria-hidden>
              {zones.map((zone) => { const box = safeZoneBox(zone.region); return box ? (
                <span className="absolute flex items-center justify-center text-xs font-medium" key={zone.region} style={{ top: `${box.top}%`, left: `${box.left}%`, width: `${box.width}%`, height: `${box.height}%`, backgroundImage: "repeating-linear-gradient(45deg, currentColor 0 1px, transparent 1px 7px)", opacity: 0.55 }}>
                  <span className="vs-small bg-background px-1">{zone.region}</span>
                </span>) : null; })}
            </div>
            <ul className="text-sm">{zones.map((zone) => <li key={zone.region}><strong>{zone.region}</strong> (hatched on the frame): {zone.instruction}</li>)}</ul>
          </div>
        ) : null}
      </div>

      <form className={`${PANEL} space-y-3`} data-visual-style-type-form onSubmit={(event) => {
        event.preventDefault();
        void onSave({ imageTypes: { [row.key]: { guidance, avoid: textLines(avoid) } } }, `Edited the ${row.key} guidance`, "Guidance saved");
      }}>
        <h5 className="font-semibold">Guidance</h5>
        <LabelledArea hint={`Added to the brand's rules for this type${row.inheritsFrom ? ` and to what ${row.inheritsFrom} says` : ""}; it never replaces them.`} label="What this type should look like" onChange={setGuidance} rows={4} value={guidance} />
        <LabelledArea hint="One per line. Added to what the brand and any parent type already avoid." label="Avoid in this type" onChange={setAvoid} rows={3} value={avoid} />
        <Button disabled={busy !== null || row.retired} type="submit"><Save aria-hidden /> Save guidance</Button>
      </form>

      <div className={`${PANEL} space-y-2`} data-visual-style-source-order>
        <h5 className="font-semibold">Sources, best first</h5>
        <p className="text-sm text-muted-foreground">{ownSources ? "Where pictures of this type may come from, in the order to try them." : `Taken from ${row.inheritsFrom ?? "its family"}. Change the order to give this type its own.`}</p>
        <ol className="space-y-2">
          {sources.map((source, index) => (
            <li className="flex flex-wrap items-center gap-2 vs-tile bg-background p-2 text-sm" data-source-row={source} key={source}>
              <span className="tabular-nums font-medium">{index + 1}.</span><span className="[&_svg]:size-4">{SOURCE_ICONS[source]}</span>
              <span className="font-medium">{SOURCE_LABELS[source]?.label ?? source}</span><span className="text-muted-foreground">{SOURCE_LABELS[source]?.detail}</span>
              <span className="ml-auto flex gap-1">
                <Button aria-label={`Move ${SOURCE_LABELS[source]?.label} up`} disabled={index === 0 || busy !== null || row.retired} onClick={() => void onSave({ imageTypes: { [row.key]: { sources: moveSource(sources, index, -1) } } }, `Reordered the ${row.key} sources`, "Sources reordered")} size="sm" type="button" variant="ghost"><ArrowUp aria-hidden /> Move up</Button>
                <Button aria-label={`Move ${SOURCE_LABELS[source]?.label} down`} disabled={index === sources.length - 1 || busy !== null || row.retired} onClick={() => void onSave({ imageTypes: { [row.key]: { sources: moveSource(sources, index, 1) } } }, `Reordered the ${row.key} sources`, "Sources reordered")} size="sm" type="button" variant="ghost"><ArrowDown aria-hidden /> Move down</Button>
                {sources.length > 1 ? <Button aria-label={`Stop using ${SOURCE_LABELS[source]?.label}`} disabled={busy !== null || row.retired} onClick={() => void onSave({ imageTypes: { [row.key]: { sources: sources.filter((item) => item !== source) } } }, `Removed ${source} from the ${row.key} sources`, "Source removed")} size="sm" type="button" variant="ghost"><Trash2 aria-hidden /> Remove</Button> : null}
              </span>
            </li>
          ))}
        </ol>
        {unusedSources(sources).length ? (
          <div className="flex flex-wrap gap-2">{unusedSources(sources).map((source) => (
            <Button disabled={busy !== null || row.retired} key={source} onClick={() => void onSave({ imageTypes: { [row.key]: { sources: [...sources, source] } } }, `Allowed ${source} for the ${row.key} type`, "Source added")} size="sm" type="button" variant="secondary"><Plus aria-hidden /> Allow {SOURCE_LABELS[source].label.toLowerCase()}</Button>
          ))}</div>
        ) : null}
      </div>

      <div className={`${PANEL} space-y-2`} data-visual-style-examples>
        <h5 className="font-semibold">Examples</h5>
        <p className="text-sm text-muted-foreground">Good pictures and ones to avoid, for this type only.{row.inheritsFrom ? ` ${row.inheritsFrom}'s examples are not shared with it.` : ""}</p>
        <ExamplesGrid door={door} guard={guard} pictureUrl={pictureUrl} profile={profile} readOnly={row.retired} reload={reload} scope={row.key} setNote={setNote} thumbnail={row.thumbnail ? row.smallestWidthPx : null} uploadPicture={uploadPicture} />
      </div>

      <div className={`${PANEL} space-y-3`} data-visual-style-effective>
        <h5 className="font-semibold">The rules in effect</h5>
        <p className="text-sm text-muted-foreground">What an agent or an editor gets for this type once the brand, the family, the use and any parent type are added together. Each line says where it came from.</p>
        {effective.status === "loading" ? <p className="flex items-center gap-2 text-sm" role="status"><Loader aria-hidden className="size-4 animate-spin" /> Working out the effective rules…</p> : null}
        {effective.status === "none" ? <p className="flex items-center gap-2 text-sm" role="status"><Info aria-hidden className="size-4" /> {effective.reason}</p> : null}
        {effective.status === "ready" ? <EffectiveRules view={effective.view} /> : null}
      </div>
    </div>
  );
}

function SourceTag({ source }: { source: string }) {
  return <span className="ml-2 inline-flex items-center gap-1 vs-pill bg-secondary px-2 py-0.5 text-xs text-secondary-foreground" data-rule-source><CornerDownRight aria-hidden className="size-3" /> from {source}</span>;
}

function EffectiveRules({ view }: { view: ReturnType<typeof effectiveView> }) {
  const lines = (title: string, items: { text: string; source: string }[]) => items.length ? (
    <div className="space-y-1"><h6 className="text-sm font-medium">{title}</h6><ul className="space-y-1 text-sm">{items.map((item, index) => <li data-effective-line key={`${item.text}-${index}`}>{item.text}<SourceTag source={item.source} /></li>)}</ul></div>
  ) : null;
  const single = (title: string, item: { text: string; source: string } | null) => item ? (
    <div className="space-y-1"><h6 className="text-sm font-medium">{title}</h6><p className="text-sm" data-effective-line>{item.text}<SourceTag source={item.source} /></p></div>
  ) : null;
  return (
    <div className="space-y-3" data-effective-rules>
      {single("Master prompt", view.masterPrompt)}
      {lines("Guidance, in order", view.guidance)}
      {lines("Always avoid", view.avoid)}
      {single("Size", view.sizes)}
      {single("Where it is shown", view.display)}
      {single("Sources", view.sources)}
      {view.removed.length ? <div className="space-y-1"><h6 className="text-sm font-medium">Taken off by this type</h6><ul className="list-disc space-y-1 pl-5 text-sm">{view.removed.map((entry) => <li key={entry}>{entry}</li>)}</ul></div> : null}
      {view.constraints.length ? (
        <div className="space-y-1"><h6 className="flex items-center gap-2 text-sm font-medium"><Lock aria-hidden className="size-3.5" /> Binding rules (cannot be loosened)</h6>
          <ul className="space-y-1 text-sm">{view.constraints.map((rule) => <li key={rule.id}>{rule.text}<SourceTag source="Brand" /></li>)}</ul></div>
      ) : null}
    </div>
  );
}

// --- examples grid ------------------------------------------------------------------------------------------------------------------------------------

function ExamplePicture({ example, pictureUrl, smallest }: { example: Example; pictureUrl: ExampleUrl; smallest: number | null }) {
  const [url, setUrl] = useState<string | null | undefined>(undefined);
  useEffect(() => { let current = true; void pictureUrl(example.attachmentId).then((found) => { if (current) setUrl(found); }, () => { if (current) setUrl(null); }); return () => { current = false; }; }, [example.attachmentId, pictureUrl]);
  const alt = example.note ? `${example.kind === "exemplar" ? "Good example" : "Avoid this"}: ${example.note}` : example.kind === "exemplar" ? "Good example picture" : "Picture to avoid";
  if (url === undefined) return <div className="flex aspect-video items-center justify-center vs-tile bg-background text-sm text-muted-foreground" role="status"><Loader aria-hidden className="mr-2 size-4 animate-spin" /> Loading the picture…</div>;
  if (url === null) return <div className="flex aspect-video items-center justify-center vs-tile bg-background text-sm text-muted-foreground"><CircleAlert aria-hidden className="mr-2 size-4" /> The picture could not be loaded</div>;
  return (
    <div className="space-y-1">
      <img alt={alt} className="aspect-video w-full vs-tile bg-background object-cover" src={url} />
      {smallest ? <div className="flex items-center gap-2 text-xs text-muted-foreground"><img alt="" className="vs-small bg-background object-cover" src={url} style={{ width: Math.min(smallest, 160), aspectRatio: "16 / 9" }} /> As a card: {smallest}px</div> : null}
    </div>
  );
}

function ExamplesGrid({ profile, scope, door, guard, reload, setNote, uploadPicture, pictureUrl, thumbnail, readOnly = false }: {
  profile: Profile; scope: string; door: ImageDoor; guard: string; reload: () => Promise<void>; setNote: (note: Note | null) => void; uploadPicture: UploadExample; pictureUrl: ExampleUrl;
  thumbnail: number | null; readOnly?: boolean;
}) {
  const examples = examplesFor(profile, scope);
  const [adding, setAdding] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<"exemplar" | "negative">("exemplar");
  const [noteText, setNoteText] = useState("");
  const [send, setSend] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  const reset = () => { setAdding(false); setFile(null); setNoteText(""); setSend(false); setKind("exemplar"); setProblem(null); };
  const add = async () => {
    if (!file) { setProblem("Choose a picture first."); return; }
    const refused = pictureProblem(file);
    if (refused) { setProblem(refused); return; }
    if (!noteText.trim()) { setProblem(kind === "exemplar" ? "Say in a few words why this is a good example." : "Say in a few words what to avoid about this picture."); return; }
    setWorking("Uploading the picture…"); setProblem(null);
    try {
      const { attachmentId } = await uploadPicture(file, kind);
      setWorking("Adding it to the style…");
      const answer = await door("image_profile_example_add", { attachmentId, imageType: scope, kind, note: noteText.trim(), sendToProvider: send, reason: "Added an example picture in Administration", expectedCurrentVersionId: guard });
      if (!answer.ok) { setProblem(answer.error.code === "stale_version" ? "Someone else changed the style while you were adding the picture. It has been reloaded; add it again." : answer.error.message); if (answer.error.code === "stale_version") await reload(); return; }
      await reload(); reset(); setNote({ tone: "ok", text: `Picture added as a ${kind === "exemplar" ? "good example" : "picture to avoid"} (version ${answer.result.versionNumber}).` });
    } catch (error) { setProblem(error instanceof Error ? error.message : "The picture could not be added."); } finally { setWorking(null); }
  };
  const remove = async (example: Example) => {
    setWorking("Removing…");
    const answer = await door("image_profile_example_remove", { attachmentId: example.attachmentId, imageType: scope, reason: "Removed an example picture in Administration", expectedCurrentVersionId: guard });
    setWorking(null);
    if (!answer.ok) { setNote({ tone: "error", text: answer.error.message }); if (answer.error.code === "stale_version") await reload(); return; }
    await reload(); setNote({ tone: "ok", text: `Picture removed (version ${answer.result.versionNumber}). Older versions of the style still list it.` });
  };

  return (
    <div className="space-y-3" data-examples-grid={scope}>
      {examples.length === 0 && !adding ? <p className="flex items-center gap-2 text-sm text-muted-foreground" data-examples-empty><Info aria-hidden className="size-4" /> No example pictures yet.</p> : null}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {examples.map((example) => (
          <li className="space-y-2 vs-tile bg-background/60 p-2" data-example={example.attachmentId} data-example-kind={example.kind} key={example.attachmentId}>
            <ExamplePicture example={example} pictureUrl={pictureUrl} smallest={thumbnail} />
            <p className="flex items-center gap-1.5 text-sm font-medium">{example.kind === "exemplar" ? <><ThumbsUp aria-hidden className="size-4" /> Good example</> : <><Ban aria-hidden className="size-4" /> Avoid this</>}</p>
            {example.note ? <p className="text-sm">{example.note}</p> : null}
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">{example.sendToProvider ? <><Send aria-hidden className="size-3.5" /> Sent to the image model as a style reference</> : <><CircleOff aria-hidden className="size-3.5" /> Not sent to the image model</>}</p>
            {readOnly ? null : <Button aria-label={`Remove this example: ${example.note || example.attachmentId}`} disabled={working !== null} onClick={() => void remove(example)} size="sm" type="button" variant="ghost"><Trash2 aria-hidden /> Remove</Button>}
          </li>
        ))}
      </ul>
      {readOnly ? null : !adding ? <Button data-add-picture onClick={() => setAdding(true)} type="button" variant="secondary"><ImagePlus aria-hidden /> Add picture</Button> : (
        <form className="space-y-3 vs-tile bg-background/60 p-3" data-add-picture-form onSubmit={(event) => { event.preventDefault(); void add(); }}>
          <h6 className="font-medium">Add a picture</h6>
          <div className="space-y-1">
            <label className="text-sm font-medium" htmlFor={`picture-${scope}`}>Picture (PNG, JPEG or WebP, up to 10 MB)</label>
            <input accept="image/png,image/jpeg,image/webp" className="block w-full text-sm file:mr-3 file:vs-small file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:font-medium" id={`picture-${scope}`} onChange={(event) => { setFile(event.target.files?.[0] ?? null); setProblem(null); }} ref={picker} type="file" />
            {file ? <p className="text-xs text-muted-foreground">Chosen: {file.name}</p> : null}
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="What kind of picture is it?">
            <Button aria-pressed={kind === "exemplar"} onClick={() => setKind("exemplar")} size="sm" type="button" variant={kind === "exemplar" ? "default" : "secondary"}>{kind === "exemplar" ? <Check aria-hidden /> : <ThumbsUp aria-hidden />} Good example</Button>
            <Button aria-pressed={kind === "negative"} onClick={() => setKind("negative")} size="sm" type="button" variant={kind === "negative" ? "default" : "secondary"}>{kind === "negative" ? <Check aria-hidden /> : <Ban aria-hidden />} Avoid this</Button>
          </div>
          <LabelledArea label={kind === "exemplar" ? "Why is it a good example?" : "What should be avoided?"} onChange={setNoteText} rows={2} value={noteText} />
          <div className="space-y-1">
            <Button aria-pressed={send} onClick={() => setSend((value) => !value)} size="sm" type="button" variant={send ? "default" : "secondary"}>{send ? <Check aria-hidden /> : <CircleOff aria-hidden />} Send to the image model as a style reference: {send ? "Yes" : "No"}</Button>
            <p className="text-xs text-muted-foreground">Leave this off if the picture shows identifiable people or logos. Only a person can turn it on.</p>
          </div>
          {problem ? <p className="flex items-center gap-2 text-sm" role="alert"><CircleAlert aria-hidden className="size-4" /> <strong>Problem:</strong> {problem}</p> : null}
          {working ? <p className="flex items-center gap-2 text-sm" role="status"><Loader aria-hidden className="size-4 animate-spin" /> {working}</p> : null}
          <div className="flex gap-2"><Button disabled={working !== null} type="submit"><ImagePlus aria-hidden /> Add this picture</Button><Button disabled={working !== null} onClick={reset} type="button" variant="ghost">Cancel</Button></div>
        </form>
      )}
    </div>
  );
}
