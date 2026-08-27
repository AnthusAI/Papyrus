"use client";

import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import type { EditionPresentationFormat } from "../lib/content-types";
import { SITE_BRAND, enforcePresentation, getPresentationChoices } from "../lib/site-brand";
import { configureAmplifyClient } from "./amplify-client-provider";
import { isUnauthenticatedError, loadReaderSessionSnapshot } from "./reader-auth-state";

export type ReaderThemeSetting = "system" | "light" | "dark";
export type ReaderMotionSetting = "standard" | "low";

export type ReaderSettings = {
  presentation: EditionPresentationFormat;
  theme: ReaderThemeSetting;
  motion: ReaderMotionSetting;
};

export type ReaderSettingsSource = "local" | "cloud";

export type ReaderSettingsResolution = {
  settings: ReaderSettings;
  source: ReaderSettingsSource;
  signedIn: boolean;
  email?: string | null;
  userProfileId?: string | null;
  avatarHash?: string | null;
};

type DataClientErrors = Array<{ message?: string | null } | string | null> | null | undefined;
type ReaderSettingsResult = {
  email?: string | null;
  userProfileId?: string | null;
  avatarHash?: string | null;
  settings?: ReaderSettings | null;
};
type RawReaderSettingsResult = {
  email?: string | null;
  userProfileId?: string | null;
  avatarHash?: string | null;
  settings?: unknown;
};

const USER_POOL_AUTH_MODE = "userPool";
const SETTINGS_STORAGE_KEY = "papyrus:reader-settings";
const LEGACY_PRESENTATION_STORAGE_KEY = "papyrus:presentation";
const LEGACY_PRESENTATION_COOKIE = "papyrus-presentation";
const LEGACY_COOKIE_CLEANUP_STORAGE_KEY = "papyrus:legacy-presentation-cookie-cleaned";
const SETTINGS_EVENT = "papyrus:settings-changed";

export const DEFAULT_READER_SETTINGS: ReaderSettings = {
  presentation: enforcePresentation(SITE_BRAND.defaultPresentation),
  theme: "system",
  motion: "standard",
};

const ALL_PRESENTATION_OPTIONS: Array<{
  value: EditionPresentationFormat;
  label: string;
  description: string;
}> = [
  {
    value: "newspaper",
    label: "Newspaper",
    description: "Planned pages, feature headlines, and exact continuations.",
  },
  {
    value: "blog",
    label: "Blog",
    description: "Continuous sections with measured Pretext text and no page jumps.",
  },
  {
    value: "magazine",
    label: "Magazine",
    description: "Feature-led section spreads using the same edition items.",
  },
];

const ALLOWED_PRESENTATION_CHOICES = new Set<EditionPresentationFormat>(getPresentationChoices());

export const PRESENTATION_OPTIONS = ALL_PRESENTATION_OPTIONS.filter((option) =>
  ALLOWED_PRESENTATION_CHOICES.has(option.value),
);

export const THEME_OPTIONS: Array<{
  value: ReaderThemeSetting;
  label: string;
}> = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export const MOTION_OPTIONS: Array<{
  value: ReaderMotionSetting;
  label: string;
}> = [
  { value: "standard", label: "Standard" },
  { value: "low", label: "Low Motion" },
];

export function readLocalReaderSettings(): ReaderSettings {
  if (typeof window === "undefined") return DEFAULT_READER_SETTINGS;
  cleanupLegacyPresentationCookie();
  const parsed = parseStoredSettings(window.localStorage.getItem(SETTINGS_STORAGE_KEY));
  const legacyPresentation = readPresentationValue(window.localStorage.getItem(LEGACY_PRESENTATION_STORAGE_KEY));
  return normalizeReaderSettings({
    ...parsed,
    presentation: parsed?.presentation ?? legacyPresentation ?? DEFAULT_READER_SETTINGS.presentation,
  });
}

export function writeLocalReaderSettings(settings: ReaderSettings) {
  if (typeof window === "undefined") return;
  cleanupLegacyPresentationCookie();
  const normalized = normalizeReaderSettings(settings);
  window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(normalized));
  window.localStorage.setItem(LEGACY_PRESENTATION_STORAGE_KEY, normalized.presentation);
  applyReaderTheme(normalized.theme);
  window.dispatchEvent(new CustomEvent(SETTINGS_EVENT, { detail: normalized }));
}

export function applyReaderTheme(theme: ReaderThemeSetting) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.papyrusTheme = theme;
  applyReaderThemeClass(theme);
  updateThemeMeta(theme);
}

export function subscribeReaderSettingsChanges(listener: (settings: ReaderSettings) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const notify = () => listener(readLocalReaderSettings());
  const handleSettingsEvent = (event: Event) => {
    const detail = "detail" in event ? (event as CustomEvent<unknown>).detail : null;
    listener(normalizeReaderSettings(detail));
  };
  const handleStorageEvent = (event: StorageEvent) => {
    if (event.key === SETTINGS_STORAGE_KEY || event.key === LEGACY_PRESENTATION_STORAGE_KEY) notify();
  };
  window.addEventListener(SETTINGS_EVENT, handleSettingsEvent);
  window.addEventListener("storage", handleStorageEvent);
  return () => {
    window.removeEventListener(SETTINGS_EVENT, handleSettingsEvent);
    window.removeEventListener("storage", handleStorageEvent);
  };
}

export async function resolveReaderSettings(): Promise<ReaderSettingsResolution> {
  const localSettings = readLocalReaderSettings();
  writeLocalReaderSettings(localSettings);
  const session = await loadReaderSessionSnapshot();
  if (!session.hasSession) {
    return { settings: localSettings, source: "local", signedIn: false };
  }

  try {
    const remote = await getRemoteReaderSettings();
    if (remote.settings) {
      writeLocalReaderSettings(remote.settings);
      return {
        settings: remote.settings,
        source: "cloud",
        signedIn: true,
        email: remote.email,
        userProfileId: remote.userProfileId,
        avatarHash: remote.avatarHash,
      };
    }
    const saved = await saveRemoteReaderSettings(localSettings);
    return {
      settings: saved.settings ?? localSettings,
      source: "cloud",
      signedIn: true,
      email: saved.email,
      userProfileId: saved.userProfileId,
      avatarHash: saved.avatarHash,
    };
  } catch (error) {
    if (isUnauthenticatedError(error)) {
      return { settings: localSettings, source: "local", signedIn: false };
    }
    throw error;
  }
}

export async function saveReaderSettings(settings: ReaderSettings): Promise<ReaderSettingsResolution> {
  const normalized = normalizeReaderSettings(settings);
  writeLocalReaderSettings(normalized);
  const session = await loadReaderSessionSnapshot();
  if (!session.hasSession) {
    return { settings: normalized, source: "local", signedIn: false };
  }
  const saved = await saveRemoteReaderSettings(normalized);
  const savedSettings = saved.settings ?? normalized;
  writeLocalReaderSettings(savedSettings);
  return {
    settings: savedSettings,
    source: "cloud",
    signedIn: true,
    email: saved.email,
    userProfileId: saved.userProfileId,
    avatarHash: saved.avatarHash,
  };
}

async function getRemoteReaderSettings(): Promise<ReaderSettingsResult> {
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    queries: {
      getReaderSettings(options: { authMode: typeof USER_POOL_AUTH_MODE }): Promise<{
        data?: RawReaderSettingsResult | null;
        errors?: DataClientErrors;
      }>;
    };
  };
  const response = await client.queries.getReaderSettings({ authMode: USER_POOL_AUTH_MODE });
  assertNoDataErrors(response.errors, "get reader settings");
  return normalizeReaderSettingsResult(response.data);
}

async function saveRemoteReaderSettings(settings: ReaderSettings): Promise<ReaderSettingsResult> {
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as {
    mutations: {
      updateReaderSettings(
        input: { settings: ReaderSettings },
        options: { authMode: typeof USER_POOL_AUTH_MODE },
      ): Promise<{
        data?: RawReaderSettingsResult | null;
        errors?: DataClientErrors;
      }>;
    };
  };
  const response = await client.mutations.updateReaderSettings({ settings }, { authMode: USER_POOL_AUTH_MODE });
  assertNoDataErrors(response.errors, "update reader settings");
  return normalizeReaderSettingsResult(response.data);
}

function normalizeReaderSettingsResult(value: RawReaderSettingsResult | null | undefined): ReaderSettingsResult {
  if (!value) return {};
  return {
    email: typeof value.email === "string" && value.email.trim() ? value.email.trim() : null,
    userProfileId: value.userProfileId ?? null,
    avatarHash: typeof value.avatarHash === "string" && value.avatarHash.trim() ? value.avatarHash.trim() : null,
    settings: value.settings ? normalizeReaderSettings(value.settings) : null,
  };
}

export function normalizeReaderSettings(value: unknown): ReaderSettings {
  const candidate = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    presentation: normalizePresentation(candidate.presentation),
    theme: normalizeTheme(candidate.theme),
    motion: normalizeMotion(candidate.motion),
  };
}

function parseStoredSettings(value: string | null): Partial<ReaderSettings> | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== "object") return null;
    return parsed as Partial<ReaderSettings>;
  } catch {
    return null;
  }
}

function normalizePresentation(value: unknown): EditionPresentationFormat {
  const normalized =
    value === "blog" || value === "magazine" || value === "newspaper"
      ? value
      : DEFAULT_READER_SETTINGS.presentation;
  return enforcePresentation(normalized);
}

function normalizeTheme(value: unknown): ReaderThemeSetting {
  return value === "light" || value === "dark" || value === "system" ? value : DEFAULT_READER_SETTINGS.theme;
}

function normalizeMotion(value: unknown): ReaderMotionSetting {
  return value === "low" || value === "standard" ? value : DEFAULT_READER_SETTINGS.motion;
}

function readPresentationValue(value: string | null | undefined): EditionPresentationFormat | null {
  if (value !== "newspaper" && value !== "blog" && value !== "magazine") return null;
  return enforcePresentation(value);
}

function cleanupLegacyPresentationCookie() {
  if (typeof document === "undefined" || typeof window === "undefined") return;
  if (window.localStorage.getItem(LEGACY_COOKIE_CLEANUP_STORAGE_KEY) === "true") return;
  document.cookie = `${LEGACY_PRESENTATION_COOKIE}=; path=/; max-age=0; samesite=lax`;
  window.localStorage.setItem(LEGACY_COOKIE_CLEANUP_STORAGE_KEY, "true");
}

function updateThemeMeta(theme: ReaderThemeSetting) {
  const colorScheme = theme === "dark" ? "dark" : theme === "light" ? "light" : "light dark";
  let meta = document.querySelector<HTMLMetaElement>('meta[name="color-scheme"][data-papyrus-theme-meta="true"]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "color-scheme";
    meta.setAttribute("data-papyrus-theme-meta", "true");
    document.head.appendChild(meta);
  }
  meta.content = colorScheme;
}

function applyReaderThemeClass(theme: ReaderThemeSetting) {
  if (typeof document === "undefined") return;
  const isDark = resolveReaderThemeIsDark(theme);
  document.documentElement.classList.toggle("dark", isDark);
  document.documentElement.classList.toggle("dark-theme", isDark);
  document.documentElement.classList.toggle("light", !isDark);
  document.documentElement.classList.toggle("light-theme", !isDark);
}

function resolveReaderThemeIsDark(theme: ReaderThemeSetting) {
  if (theme === "dark") return true;
  if (theme === "light") return false;
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function assertNoDataErrors(errors: DataClientErrors, operation: string): void {
  if (!errors?.length) return;
  throw new Error(`${operation} failed: ${errors.map(formatDataError).join("; ")}`);
}

function formatDataError(error: { message?: string | null } | string | null): string {
  if (typeof error === "string") return error;
  return error?.message ?? "GraphQL data operation failed.";
}
