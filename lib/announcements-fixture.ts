import type { AnnouncementsApi } from "./announcements-client";
import type { AnnouncementRow, AnnouncementSettings, XStatus } from "./announcements-model";
import type { AnnouncementsSource } from "./announcements-data";

/** Demo data for `?demo=1` and the local preview only. Nothing here is read by a signed-in site. */
const DEMO_REDIRECT_HANDLE = "mom_test";

const DEMO_ROWS: AnnouncementRow[] = [
  {
    id: "a1", storyTitle: "The machines that audit other machines", state: "dry_run", at: "2026-11-13T09:01:00Z",
    text: "New on Machines on Machines: how automated auditors check other automated systems, and where they fall short.", link: "https://machines.example/articles/auditors?utm_source=x&utm_medium=social&utm_campaign=announcement", weightedLength: 126,
  },
  {
    id: "a2", storyTitle: "Why the hardware shortage is a software story", state: "blocked", blockedReason: "Paused", at: "2026-11-13T10:30:00Z",
    text: "A shortage of chips is changing how software gets written. Our latest on what teams are doing about it.", link: "https://machines.example/articles/shortage?utm_source=x&utm_medium=social&utm_campaign=announcement", weightedLength: 119,
  },
  {
    id: "a3", storyTitle: "Reading a model's mind, one neuron at a time", state: "posted", at: "2026-11-12T14:00:00Z", postUrl: "https://x.example/mom_test/status/1", costUsd: 0.2,
    text: "Interpretability researchers can now trace a single answer back to its parts. What that does and does not tell us.", link: "https://machines.example/articles/neurons?utm_source=x&utm_medium=social&utm_campaign=announcement", weightedLength: 133,
  },
];

export const demoAnnouncementsSource: AnnouncementsSource = { list: async () => DEMO_ROWS };

export function createFixtureApi(initial?: { connected?: boolean }): AnnouncementsApi {
  let settings: AnnouncementSettings = {
    mode: "off",
    pause: { paused: false, reason: null, detail: null, by: null, at: null },
    rules: { minStars: 5, storyTypes: ["article", "post"], sections: [] },
    budget: null,
    prices: { createPost: 0.015, createPostWithUrl: 0.2, deletePost: 0.01, readPost: 0.005, asOf: "2026-11-12" },
    labelConfirmed: false,
  };
  let status: XStatus = {
    clientId: null, secretSaved: false, secretSavedAt: null, connection: "not_connected", handle: null, accountId: null, scopes: [],
    connectedAt: null, lastRefreshAt: null, refreshHealth: { healthy: false, error: null },
  };
  if (initial?.connected) status = connectedStatus({ ...status, clientId: "demo-client-id", secretSaved: true, secretSavedAt: "2026-11-13T08:00:00Z" });
  const api = (async (operation: string, input: Record<string, unknown> = {}) => {
    switch (operation) {
      case "announcementsSettings": return { ok: true, settings };
      case "announcementsXStatus": return { ok: true, status };
      case "announcementsXUsage": return status.connection === "connected" ? { ok: true, usage: { postsThisCycle: "12", postCap: "2000", capResetDay: 9 } } : { ok: false, error: "not_connected", message: "No X account is connected." };
      case "announcementsXSaveApp":
        status = { ...status, clientId: String(input.clientId), secretSaved: true, secretSavedAt: "2026-11-13T08:00:00Z" };
        return { ok: true, status };
      case "announcementsXBegin": return { ok: true, authorizeUrl: "#demo-x-authorize", state: "demo" };
      case "announcementsXComplete": status = connectedStatus(status); return { ok: true, status };
      case "announcementsXDisconnect":
        status = { ...status, connection: "not_connected", handle: null, accountId: null, scopes: [], connectedAt: null, lastRefreshAt: null, refreshHealth: { healthy: false, error: null } };
        settings = { ...settings, pause: { paused: true, reason: "disconnected", detail: "The X account was disconnected.", by: "demo", at: new Date().toISOString() } };
        return { ok: true, status, settings };
      case "announcementsPause":
        settings = { ...settings, pause: input.paused ? { paused: true, reason: "manual", detail: "Paused by hand.", by: "demo", at: new Date().toISOString() } : { paused: false, reason: null, detail: null, by: null, at: null } };
        return { ok: true, settings };
      case "announcementsSaveSettings": {
        const proposed = input.settings as AnnouncementSettings;
        if (proposed.rules.minStars < 3) return { ok: false, error: "below_quality_floor", message: "Announcements can't go below your quality floor of 3 stars." };
        settings = { ...settings, ...proposed, pause: settings.pause };
        return { ok: true, settings };
      }
      default: return { ok: false, error: "unknown_operation" };
    }
  }) as unknown as AnnouncementsApi;
  return api;
}

function connectedStatus(base: XStatus): XStatus {
  return {
    ...base, connection: "connected", handle: DEMO_REDIRECT_HANDLE, accountId: "1001", scopes: ["tweet.write", "tweet.read", "users.read", "offline.access"],
    connectedAt: "2026-11-13T08:05:00Z", lastRefreshAt: "2026-11-13T08:05:00Z", refreshHealth: { healthy: true, error: null },
  };
}
