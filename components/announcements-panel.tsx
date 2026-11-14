"use client";

import {
  Ban, Check, CircleCheck, CirclePause, CirclePlay, CircleX, Copy, FlaskConical, KeyRound, Megaphone, Plug, Power, Save, Send, Star, TriangleAlert, Unplug,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { callAnnouncements, type AnnouncementsApi } from "../lib/announcements-client";
import { announcementsSource, AnnouncementsBackendNotDeployed, type AnnouncementsSource } from "../lib/announcements-data";
import { createFixtureApi, demoAnnouncementsSource } from "../lib/announcements-fixture";
import {
  MODE_OPTIONS, QUALITY_FLOOR_STARS, SETUP_INTRO, STAR_CHOICES, STORY_TYPE_OPTIONS, X_PRICING_URL, X_STATE_STORAGE_KEY,
  callbackUrl, connectionWords, failureText, formatDate, formatMoney, formatWhen, modeBlockers, pauseText, setupSteps, stateWords, toggled,
  type AnnouncementFailure, type AnnouncementMode, type AnnouncementRow, type AnnouncementSettings, type XStatus, type XUsage,
} from "../lib/announcements-model";
import { getPublicNewsroomBasePath } from "../lib/newsroom-base-path";

type Message = { kind: "ok" | "problem"; text: string } | null;
type Section = { id: string; title: string };
const isFailure = (value: { ok: boolean }): value is AnnouncementFailure => value.ok === false;

const MODE_ICON = { off: Power, dry_run: FlaskConical, on: Send } as const;
const PRICE_FIELDS: { key: "createPost" | "createPostWithUrl" | "deletePost" | "readPost"; label: string }[] = [
  { key: "createPostWithUrl", label: "Post with a link (every announcement)" },
  { key: "createPost", label: "Post without a link" },
  { key: "deletePost", label: "Delete a post" },
  { key: "readPost", label: "Read a post" },
];

/**
 * Administration, Announcements: the pause switch, the plain setup guide, the X app's keys (the secret is write only), the
 * connected account, the mode, the rules, the budget and prices, and the list of announcements. Admins change; editors read.
 * It reads on open and after each action and never subscribes to anything.
 */
export function AnnouncementsPanel({ isAdmin, isDemo, sections }: { isAdmin: boolean; isDemo: boolean; sections: Section[] }) {
  const api: AnnouncementsApi = useMemo(() => (isDemo ? createFixtureApi() : callAnnouncements), [isDemo]);
  const source: AnnouncementsSource = isDemo ? demoAnnouncementsSource : announcementsSource;
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => { live.current = false; };
  }, []);

  const [saved, setSaved] = useState<AnnouncementSettings | null>(null);
  const [draft, setDraft] = useState<AnnouncementSettings | null>(null);
  const [status, setStatus] = useState<XStatus | null>(null);
  const [usage, setUsage] = useState<XUsage | null>(null);
  const [usageProblem, setUsageProblem] = useState<string | null>(null);
  const [rows, setRows] = useState<AnnouncementRow[] | null>(null);
  const [rowsProblem, setRowsProblem] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [copied, setCopied] = useState(false);

  const callback = useMemo(() => callbackUrl(typeof window === "undefined" ? "https://your-site.example" : window.location.origin, getPublicNewsroomBasePath()), []);

  const load = useCallback(async () => {
    const [settings, xStatus] = await Promise.all([api<{ settings: AnnouncementSettings }>("announcementsSettings"), api<{ status: XStatus }>("announcementsXStatus")]);
    if (!live.current) return;
    if (isFailure(settings)) return setProblem(failureText(settings));
    if (isFailure(xStatus)) return setProblem(failureText(xStatus));
    setProblem(null);
    setSaved(settings.settings);
    setDraft(settings.settings);
    setStatus(xStatus.status);
    setClientId((current) => current || xStatus.status.clientId || "");
    if (xStatus.status.connection === "connected") {
      const used = await api<{ usage: XUsage }>("announcementsXUsage");
      if (!live.current) return;
      if (isFailure(used)) { setUsage(null); setUsageProblem(failureText(used)); } else { setUsage(used.usage); setUsageProblem(null); }
    } else { setUsage(null); setUsageProblem(null); }
    try {
      const list = await source.list();
      if (live.current) { setRows(list); setRowsProblem(null); }
    } catch (error) {
      if (!live.current) return;
      setRows(null);
      setRowsProblem(error instanceof AnnouncementsBackendNotDeployed ? error.message : `The list could not be read: ${error instanceof Error ? error.message : String(error)}`);
    }
  }, [api, source]);

  useEffect(() => { void load(); }, [load]);

  const act = async (label: string, work: () => Promise<Message>) => {
    setBusy(label);
    setMessage(null);
    try {
      const outcome = await work();
      if (live.current) setMessage(outcome);
    } finally {
      if (live.current) setBusy(null);
    }
  };

  const dirty = Boolean(saved && draft && JSON.stringify(saved) !== JSON.stringify(draft));
  const disabled = !isAdmin || busy !== null;

  const saveApp = () => act("app", async () => {
    const result = await api("announcementsXSaveApp", { clientId, clientSecret });
    if (isFailure(result)) return { kind: "problem", text: failureText(result) };
    setClientSecret("");
    setReplacing(false);
    await load();
    return { kind: "ok", text: "Secret saved. It is stored encrypted and will not be shown again." };
  });

  const connect = () => act("connect", async () => {
    const begun = await api<{ authorizeUrl: string; state: string }>("announcementsXBegin", { redirectUri: callback });
    if (isFailure(begun)) return { kind: "problem", text: failureText(begun) };
    if (isDemo) {
      await api("announcementsXComplete", { code: "demo", state: begun.state, redirectUri: callback });
      await load();
      return { kind: "ok", text: "Connected in the demo. No real account was contacted." };
    }
    window.sessionStorage.setItem(X_STATE_STORAGE_KEY, begun.state);
    window.location.assign(begun.authorizeUrl);
    return { kind: "ok", text: "Opening X…" };
  });

  const disconnect = () => act("disconnect", async () => {
    const result = await api("announcementsXDisconnect");
    if (isFailure(result)) return { kind: "problem", text: failureText(result) };
    await load();
    return { kind: "ok", text: "Disconnected. The permission was removed at X and the stored token was deleted. Announcements are paused." };
  });

  const setPaused = (paused: boolean) => act("pause", async () => {
    const result = await api("announcementsPause", { paused });
    if (isFailure(result)) return { kind: "problem", text: failureText(result) };
    await load();
    return { kind: "ok", text: paused ? "Announcements are paused." : "Announcements are running again." };
  });

  const saveSettings = () => act("save", async () => {
    if (!draft) return null;
    const result = await api("announcementsSaveSettings", { settings: draft });
    if (isFailure(result)) return { kind: "problem", text: failureText(result) };
    await load();
    return { kind: "ok", text: "Saved." };
  });

  const copyCallback = async () => {
    await navigator.clipboard.writeText(callback);
    setCopied(true);
    window.setTimeout(() => { if (live.current) setCopied(false); }, 2000);
  };

  if (problem) {
    return (
      <div className="announcements" data-news-desk-admin-panel="announcements">
        <Heading />
        <p className="announcements__notice" role="alert" data-announcements-problem><TriangleAlert aria-hidden="true" size={18} /> {problem}</p>
      </div>
    );
  }
  if (!saved || !draft || !status) {
    return <div className="announcements" data-news-desk-admin-panel="announcements"><Heading /><p className="announcements__quiet">Loading…</p></div>;
  }

  const patch = (changes: Partial<AnnouncementSettings>) => setDraft({ ...draft, ...changes });
  const patchRules = (changes: Partial<AnnouncementSettings["rules"]>) => setDraft({ ...draft, rules: { ...draft.rules, ...changes } });
  const connected = status.connection === "connected";

  return (
    <div className="announcements" data-news-desk-admin-panel="announcements">
      <Heading />

      <section className="announcements__pause" data-announcements-pause data-paused={saved.pause.paused ? "true" : "false"} aria-labelledby="ann-pause">
        {saved.pause.paused ? <CirclePause aria-hidden="true" size={22} /> : <CirclePlay aria-hidden="true" size={22} />}
        <div>
          <strong id="ann-pause">{saved.pause.paused ? "Announcements are paused" : "Announcements are not paused"}</strong>
          <p data-announcements-pause-text>{pauseText(saved.pause)}</p>
        </div>
        <button type="button" className="announcements__button" disabled={disabled} onClick={() => void setPaused(!saved.pause.paused)} data-announcements-pause-switch>
          {saved.pause.paused ? <><CirclePlay aria-hidden="true" size={16} /> Resume announcements</> : <><CirclePause aria-hidden="true" size={16} /> Pause announcements</>}
        </button>
      </section>

      {!isAdmin ? <p className="announcements__quiet" data-announcements-readonly>You can read this page. An admin changes it.</p> : null}
      {message ? <p className="announcements__notice" data-kind={message.kind} role="status" data-announcements-message>{message.kind === "ok" ? <Check aria-hidden="true" size={18} /> : <TriangleAlert aria-hidden="true" size={18} />} {message.text}</p> : null}

      <Card title="Set up your X account" note="A short guide. The full guide is docs/x-announcements-setup.md." id="setup">
        <p>{SETUP_INTRO}</p>
        <ol className="announcements__steps" data-announcements-steps>
          {setupSteps(callback).map((step) => (
            <li key={step.text}>
              {step.text}
              {step.copy ? (
                <span className="announcements__copy">
                  <code data-announcements-callback>{step.copy}</code>
                  <button type="button" className="announcements__button" onClick={() => void copyCallback()} data-announcements-copy>
                    {copied ? <><Check aria-hidden="true" size={16} /> Copied</> : <><Copy aria-hidden="true" size={16} /> Copy</>}
                  </button>
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      </Card>

      <Card title="X app" note="Your own developer app. You pay X for it." id="app">
        <div className="announcements__fields">
          <label className="announcements__field">
            <span>Client ID</span>
            <input value={clientId} onChange={(event) => setClientId(event.target.value)} disabled={disabled} autoComplete="off" spellCheck={false} data-announcements-client-id />
          </label>
          {status.secretSaved && !replacing ? (
            <div className="announcements__field" data-announcements-secret-saved>
              <span>Client secret</span>
              <p className="announcements__saved"><CircleCheck aria-hidden="true" size={18} /> Secret saved{status.secretSavedAt ? `, ${formatWhen(status.secretSavedAt)}` : ""}. It is not shown again.</p>
              <button type="button" className="announcements__button" disabled={disabled} onClick={() => setReplacing(true)} data-announcements-replace-secret><KeyRound aria-hidden="true" size={16} /> Replace secret</button>
            </div>
          ) : (
            <label className="announcements__field">
              <span>Client secret</span>
              <input type="password" value={clientSecret} onChange={(event) => setClientSecret(event.target.value)} disabled={disabled} autoComplete="new-password" spellCheck={false} placeholder="Paste it here once" data-announcements-secret-input />
            </label>
          )}
        </div>
        {!status.secretSaved || replacing ? (
          <div className="announcements__actions">
            <button type="button" className="announcements__button announcements__button--primary" disabled={disabled || !clientId.trim() || !clientSecret.trim()} onClick={() => void saveApp()} data-announcements-save-app>
              <Save aria-hidden="true" size={16} /> Save keys
            </button>
            {replacing ? <button type="button" className="announcements__button" onClick={() => { setReplacing(false); setClientSecret(""); }}>Cancel</button> : null}
          </div>
        ) : null}
      </Card>

      <Card title="Connected account" note="The account the site posts from." id="account">
        <p className="announcements__status" data-announcements-connection data-connection={status.connection}>
          {connected ? <CircleCheck aria-hidden="true" size={20} /> : status.connection === "needs_reconnecting" ? <TriangleAlert aria-hidden="true" size={20} /> : <Unplug aria-hidden="true" size={20} />}
          <strong>{connectionWords(status)}</strong>
        </p>
        {status.connection !== "not_connected" ? (
          <dl className="announcements__facts" data-announcements-facts>
            <div><dt>Permissions</dt><dd>{status.scopes.length ? status.scopes.join(", ") : "none"}</dd></div>
            <div><dt>Last token refresh</dt><dd>{formatWhen(status.lastRefreshAt)}</dd></div>
            <div><dt>Refresh health</dt><dd>{status.refreshHealth.healthy ? "Healthy" : `Not healthy${status.refreshHealth.error ? `: ${status.refreshHealth.error}` : ""}`}</dd></div>
            <div><dt>Posts counted by X this cycle</dt><dd data-announcements-usage>{usage ? `${usage.postsThisCycle ?? "unknown"} of ${usage.postCap ?? "unknown"}` : usageProblem ?? "unknown"}</dd></div>
          </dl>
        ) : null}
        <div className="announcements__actions">
          {connected ? (
            <button type="button" className="announcements__button" disabled={disabled} onClick={() => void disconnect()} data-announcements-disconnect><Unplug aria-hidden="true" size={16} /> Disconnect</button>
          ) : (
            <button type="button" className="announcements__button announcements__button--primary" disabled={disabled || !status.secretSaved} onClick={() => void connect()} data-announcements-connect>
              <Plug aria-hidden="true" size={16} /> Connect X account
            </button>
          )}
          {!connected && !status.secretSaved ? <span className="announcements__quiet">Save the app&apos;s keys first.</span> : null}
        </div>
      </Card>

      <Card title="Mode" note="Everything is off until you turn it on." id="mode">
        <div className="announcements__choices" role="radiogroup" aria-label="Mode" data-announcements-modes>
          {MODE_OPTIONS.map((option) => {
            const Icon = MODE_ICON[option.value];
            const selected = draft.mode === option.value;
            return (
              <button type="button" role="radio" aria-checked={selected} key={option.value} className="announcements__choice" data-selected={selected ? "true" : "false"} data-mode={option.value}
                disabled={disabled} onClick={() => patch({ mode: option.value as AnnouncementMode })}>
                <Icon aria-hidden="true" size={18} />
                <strong>{option.label}</strong>
                <span>{option.detail}</span>
                {selected ? <span className="announcements__selected"><Check aria-hidden="true" size={14} /> Selected</span> : null}
              </button>
            );
          })}
        </div>
        {modeBlockers(draft.mode, draft, status).length ? (
          <ul className="announcements__blockers" data-announcements-blockers>
            {modeBlockers(draft.mode, draft, status).map((reason) => <li key={reason}><Ban aria-hidden="true" size={16} /> {reason}</li>)}
          </ul>
        ) : null}
        <button type="button" role="switch" aria-checked={draft.labelConfirmed} className="announcements__toggle" data-selected={draft.labelConfirmed ? "true" : "false"} disabled={disabled}
          onClick={() => patch({ labelConfirmed: !draft.labelConfirmed })} data-announcements-label>
          {draft.labelConfirmed ? <CircleCheck aria-hidden="true" size={18} /> : <CircleX aria-hidden="true" size={18} />}
          This account shows X&apos;s Automated label, managed by a person&apos;s account. <em>{draft.labelConfirmed ? "Confirmed" : "Not confirmed"}</em>
        </button>
      </Card>

      <Card title="Rules" note="Which Stories are announced. References never are." id="rules">
        <div className="announcements__group">
          <span className="announcements__label" id="ann-stars">Minimum star rating (never below {QUALITY_FLOOR_STARS})</span>
          <div className="announcements__choices announcements__choices--row" role="radiogroup" aria-labelledby="ann-stars" data-announcements-stars>
            {STAR_CHOICES.map((stars) => {
              const selected = draft.rules.minStars === stars;
              return (
                <button type="button" role="radio" aria-checked={selected} key={stars} className="announcements__choice announcements__choice--small" data-selected={selected ? "true" : "false"} disabled={disabled}
                  onClick={() => patchRules({ minStars: stars })}>
                  <Star aria-hidden="true" size={16} /> <strong>{stars} stars</strong>{selected ? <span className="announcements__selected"><Check aria-hidden="true" size={14} /> Selected</span> : null}
                </button>
              );
            })}
          </div>
          <p className="announcements__quiet">Unrated Stories and model predictions never qualify.</p>
        </div>
        <div className="announcements__group">
          <span className="announcements__label">Kinds of Story</span>
          <div className="announcements__choices announcements__choices--row" data-announcements-types>
            {STORY_TYPE_OPTIONS.map((option) => {
              const selected = draft.rules.storyTypes.includes(option.value);
              return (
                <button type="button" aria-pressed={selected} key={option.value} className="announcements__choice announcements__choice--small" data-selected={selected ? "true" : "false"} disabled={disabled}
                  onClick={() => patchRules({ storyTypes: toggled(draft.rules.storyTypes, option.value) })}>
                  {selected ? <CircleCheck aria-hidden="true" size={16} /> : <CircleX aria-hidden="true" size={16} />} <strong>{option.label}</strong> <span>{selected ? "Announced" : "Not announced"}</span>
                </button>
              );
            })}
          </div>
        </div>
        <div className="announcements__group">
          <span className="announcements__label">Sections {draft.rules.sections.length === 0 ? "(all sections)" : ""}</span>
          <div className="announcements__choices announcements__choices--row" data-announcements-sections>
            {sections.map((section) => {
              const selected = draft.rules.sections.includes(section.id);
              return (
                <button type="button" aria-pressed={selected} key={section.id} className="announcements__choice announcements__choice--small" data-selected={selected ? "true" : "false"} disabled={disabled}
                  onClick={() => patchRules({ sections: toggled(draft.rules.sections, section.id) })}>
                  {selected ? <CircleCheck aria-hidden="true" size={16} /> : null} <strong>{section.title}</strong>
                </button>
              );
            })}
            {sections.length === 0 ? <span className="announcements__quiet">This site has no sections.</span> : null}
          </div>
          <p className="announcements__quiet">Choose none to announce from every section.</p>
        </div>
      </Card>

      <Card title="Budget and prices" note="Set the same limit in X's billing page." id="budget">
        <label className="announcements__field announcements__field--narrow">
          <span>Budget per X billing cycle (US dollars)</span>
          <input type="number" min="0" step="any" inputMode="decimal" value={draft.budget ?? ""} disabled={disabled} data-announcements-budget
            onChange={(event) => patch({ budget: event.target.value === "" ? null : Number(event.target.value) })} />
        </label>
        <p className="announcements__quiet">Announcements pause on their own before a post would pass this. There is no default: it depends on your wallet.</p>
        <table className="announcements__prices" data-announcements-prices>
          <caption>X&apos;s prices as of {formatDate(draft.prices.asOf)}. <a href={X_PRICING_URL} target="_blank" rel="noreferrer">X&apos;s price list</a></caption>
          <thead><tr><th scope="col">What</th><th scope="col">Price (US dollars)</th></tr></thead>
          <tbody>
            {PRICE_FIELDS.map((field) => (
              <tr key={field.key}>
                <th scope="row">{field.label}</th>
                <td><input aria-label={`${field.label} price`} type="number" min="0" step="any" value={draft.prices[field.key]} disabled={disabled}
                  onChange={(event) => patch({ prices: { ...draft.prices, [field.key]: Number(event.target.value) } })} data-price={field.key} /> <span className="announcements__quiet">{formatMoney(draft.prices[field.key])}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        <label className="announcements__field announcements__field--narrow">
          <span>Date you copied the prices from X</span>
          <input type="date" value={draft.prices.asOf} disabled={disabled} onChange={(event) => patch({ prices: { ...draft.prices, asOf: event.target.value } })} data-announcements-prices-date />
        </label>
      </Card>

      {isAdmin ? (
        <div className="announcements__savebar" data-announcements-savebar>
          <span className="announcements__quiet" data-announcements-dirty>{dirty ? "You have changes that are not saved." : "Everything shown is saved."}</span>
          <button type="button" className="announcements__button announcements__button--primary" disabled={!dirty || busy !== null} onClick={() => void saveSettings()} data-announcements-save>
            <Save aria-hidden="true" size={16} /> Save settings
          </button>
        </div>
      ) : null}

      <Card title="Announcements" note="What would be posted, and what was." id="list">
        {rowsProblem ? <p className="announcements__quiet" data-announcements-list-problem><TriangleAlert aria-hidden="true" size={16} /> {rowsProblem}</p> : null}
        {rows && rows.length === 0 ? <p className="announcements__quiet">Nothing has qualified yet.</p> : null}
        {rows ? (
          <ul className="announcements__rows" data-announcements-rows>
            {rows.map((row) => (
              <li key={row.id} data-announcement={row.id} data-state={row.state}>
                <p className="announcements__rowhead">
                  <span className="announcements__state" data-announcement-state>{row.state === "dry_run" ? <FlaskConical aria-hidden="true" size={14} /> : row.state === "posted" ? <CircleCheck aria-hidden="true" size={14} /> : row.state === "failed" ? <CircleX aria-hidden="true" size={14} /> : row.state === "blocked" ? <Ban aria-hidden="true" size={14} /> : <Megaphone aria-hidden="true" size={14} />} {stateWords(row.state)}{row.blockedReason ? `: ${row.blockedReason}` : ""}</span>
                  <strong>{row.storyTitle}</strong>
                  <span className="announcements__quiet">{formatWhen(row.at)}</span>
                </p>
                <p className="announcements__post" data-announcement-text>{row.text}</p>
                <p className="announcements__quiet">{row.link} &middot; {row.weightedLength} of 280 characters{row.costUsd ? ` · cost ${formatMoney(row.costUsd)}` : ""}{row.postUrl ? <> &middot; <a href={row.postUrl} target="_blank" rel="noreferrer">view post</a></> : null}{row.error ? ` · ${row.error}` : ""}</p>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </div>
  );
}

function Heading() {
  return (
    <header className="announcements__heading">
      <h2><Megaphone aria-hidden="true" size={24} /> Announcements</h2>
      <p>Post on your publication&apos;s X account when a Story meets the bar you set.</p>
    </header>
  );
}

function Card({ title, note, id, children }: { title: string; note: string; id: string; children: ReactNode }) {
  return (
    <section className="announcements__card" data-announcements-section={id} aria-labelledby={`ann-${id}`}>
      <header><h3 id={`ann-${id}`}>{title}</h3><span>{note}</span></header>
      {children}
    </section>
  );
}
