/** Types and plain-words helpers for Administration > Announcements. Presentation and validation hints only: the function enforces every rule. */

export type AnnouncementMode = "off" | "dry_run" | "on";
export type PauseReason = "budget" | "disconnected" | "manual";

export type AnnouncementSettings = {
  mode: AnnouncementMode;
  pause: { paused: boolean; reason: PauseReason | null; detail: string | null; by: string | null; at: string | null };
  rules: { minStars: number; storyTypes: ("article" | "post")[]; sections: string[] };
  budget: number | null;
  prices: { createPost: number; createPostWithUrl: number; deletePost: number; readPost: number; asOf: string };
  labelConfirmed: boolean;
};

export type XStatus = {
  clientId: string | null;
  secretSaved: boolean;
  secretSavedAt: string | null;
  connection: "not_connected" | "connected" | "needs_reconnecting";
  handle: string | null;
  accountId: string | null;
  scopes: string[];
  connectedAt: string | null;
  lastRefreshAt: string | null;
  refreshHealth: { healthy: boolean; error: string | null };
};

export type XUsage = { postsThisCycle: string | null; postCap: string | null; capResetDay: number | null };

export type AnnouncementFailure = { ok: false; error: string; message?: string };

/** One announcement as the announcement backend (PPY-9f4d66) lists it. Only what this page shows. */
export type AnnouncementRow = {
  id: string;
  storyTitle: string;
  state: "dry_run" | "ready" | "posting" | "posted" | "failed" | "blocked" | "withdrawn";
  blockedReason?: string | null;
  text: string;
  link: string;
  weightedLength: number;
  at: string;
  postUrl?: string | null;
  costUsd?: number | null;
  error?: string | null;
};

/** The three-star decision (PPY-0e8d66): nothing below it is public or announced. The function holds the same number. */
export const QUALITY_FLOOR_STARS = 3;
export const STAR_CHOICES = [3, 4, 5] as const;

export const MODE_OPTIONS: { value: AnnouncementMode; label: string; detail: string }[] = [
  { value: "off", label: "Off", detail: "Nothing is built or posted." },
  { value: "dry_run", label: "Dry run", detail: "Each post is built exactly, shown here, and never sent. Nothing is spent." },
  { value: "on", label: "On", detail: "Posts are sent to X as soon as a Story qualifies." },
];

export const STORY_TYPE_OPTIONS: { value: "article" | "post"; label: string }[] = [
  { value: "article", label: "Articles" },
  { value: "post", label: "Posts" },
];

/** The browser keeps the OAuth state here between leaving for X and coming back to the callback page. */
export const X_STATE_STORAGE_KEY = "papyrus.announcements.x.state";

export const X_PRICING_URL = "https://docs.x.com/x-api/getting-started/pricing";

export const SETUP_INTRO =
  "Papyrus posts on your publication's X account when a Story meets the bar you set. You need an X developer app (a paid X subscription, the blue check, does not include this) with prepaid credits; each announcement costs about $0.20.";

export function setupSteps(callbackUrl: string): { text: string; copy?: string }[] {
  return [
    { text: "On developer.x.com, sign in with your own account and create an app for this publication." },
    { text: "In the app's User authentication settings choose OAuth 2.0, App permissions \"Read and write\", and Type of app \"Web App, Automated App or Bot\". For the callback URL paste this address:", copy: callbackUrl },
    { text: "In X's billing page, buy credits and set a spending limit equal to the budget below." },
    { text: "Paste the app's Client ID and Client Secret below. The secret is stored encrypted and never shown again." },
    { text: "Choose Connect X account and sign in to X as the publication's own account." },
    { text: "Start in Dry run to see posts without sending them, then switch to On when they look right." },
  ];
}

export function callbackUrl(origin: string, newsroomBasePath: string): string {
  return `${origin.replace(/\/$/, "")}${newsroomBasePath.replace(/\/$/, "")}/settings/announcements/x/callback`;
}

export function formatMoney(amount: number): string {
  const decimals = Math.abs(amount * 100 - Math.round(amount * 100)) > 1e-9 ? 3 : 2;
  return `$${amount.toFixed(decimals)}`;
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "never";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.getUTCDate()} ${date.toLocaleString("en-GB", { month: "short", timeZone: "UTC" })} ${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")} UTC`;
}

export function formatDate(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return day;
  return `${date.getUTCDate()} ${date.toLocaleString("en-GB", { month: "short", timeZone: "UTC" })} ${date.getUTCFullYear()}`;
}

/** The pause line shown at the top of the page: who, when and why, in words (never colour alone). */
export function pauseText(pause: AnnouncementSettings["pause"]): string {
  if (!pause.paused) return "Posts follow the mode below.";
  const why =
    pause.reason === "budget" ? "the budget for this X billing cycle was reached"
    : pause.reason === "disconnected" ? "the X account is not connected"
    : "paused by hand";
  const who = pause.by && pause.by !== "system" ? ` by ${pause.by}` : "";
  const when = pause.at ? `, ${formatWhen(pause.at)}` : "";
  return `Paused${who}${when}: ${why}.${pause.detail && pause.reason !== "manual" ? ` ${pause.detail}` : ""}`;
}

export function connectionWords(status: XStatus): string {
  if (status.connection === "connected") return `Connected: @${status.handle}`;
  if (status.connection === "needs_reconnecting") return `Needs reconnecting${status.handle ? ` (@${status.handle})` : ""}`;
  return "No X account connected";
}

/** Why a mode cannot be chosen yet, in plain words. Empty means it can. The function checks the same rules. */
export function modeBlockers(mode: AnnouncementMode, settings: Pick<AnnouncementSettings, "budget" | "labelConfirmed">, status: XStatus): string[] {
  const reasons: string[] = [];
  if (mode !== "off" && status.connection !== "connected") reasons.push("Connect an X account first.");
  if (mode === "on" && !settings.labelConfirmed) reasons.push("Confirm that the account shows X's Automated label.");
  if (mode === "on" && !settings.budget) reasons.push("Enter a budget per X billing cycle.");
  return reasons;
}

export function failureText(failure: AnnouncementFailure): string {
  if (failure.message) return failure.message;
  if (failure.error === "forbidden") return "Your role cannot do this.";
  return "Announcements are not available on this site yet.";
}

export function stateWords(state: AnnouncementRow["state"]): string {
  return {
    dry_run: "Dry run: not sent", ready: "Ready", posting: "Posting", posted: "Posted", failed: "Failed", blocked: "Blocked", withdrawn: "Withdrawn",
  }[state];
}

/** The ratings the sort of the list keys to; the key of the saved section ids is stable even when a title changes. */
export function toggled<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];
}
