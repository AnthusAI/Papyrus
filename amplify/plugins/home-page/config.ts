import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { PluginRequest, PluginResolveOptions } from "../types";

/** The window default is the HTML `s-maxage` the writers set (PAPYRUS_HTML_S_MAXAGE_SECONDS): a page cannot be fresher than its edge lifetime. */
export const DEFAULT_DEBOUNCE_SECONDS = 300;
const REQUEST_KEYS = ["name", "debounceSeconds", "intervalHours"];
const FRESHNESS_KEYS = ["debounceSeconds", "intervalHours", "purge"];
const THREADS_KEYS = ["enabled", "authors", "anonymousLabel"];
const MINUTES_PER_HOUR = 60;

export type HomePageConfig = {
  /** Quiet time between the first change and the snapshot run it schedules. */
  debounceSeconds: number;
  /** A rule runs the snapshot at this interval even without changes. `null` is off. */
  intervalHours: number | null;
  /** Mirrors `homePage.freshness.purge`; the projection task does the invalidation, the backend only reports it. */
  purge: boolean;
  /** Mirrors `homePage.threads.enabled`: the Message table stream feeds the same trigger, so a new or changed Message refreshes the threads. */
  threads: boolean;
};

type ProjectionFreshness = { debounceSeconds?: unknown; intervalHours?: unknown; purge?: unknown; threads?: boolean };

function wholeSeconds(value: unknown, where: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) throw new Error(`${where} must be a whole number of seconds, at least 1`);
  return value;
}

function intervalHours(value: unknown, where: string): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value * MINUTES_PER_HOUR < 1) throw new Error(`${where} must be a number of hours, at least one minute, or null`);
  return value;
}

/**
 * `homePage.freshness` of the site's projection.json, which the projection task itself reads at run time. Returns `undefined` when
 * the site has no projection.json; throws when it has one without a `homePage` setting, because the stream would then schedule runs
 * that the task ignores.
 */
export function readProjectionFreshness(options: PluginResolveOptions): ProjectionFreshness | undefined {
  if (options.staticDir === undefined) return undefined;
  const settingsPath = resolve(options.baseDirectory ?? process.cwd(), options.staticDir, "projection.json");
  if (!existsSync(settingsPath)) return undefined;
  const settings = JSON.parse(readFileSync(settingsPath, "utf8")) as { homePage?: { freshness?: ProjectionFreshness; threads?: { enabled?: unknown } } };
  if (settings.homePage === undefined || settings.homePage === null) {
    throw new Error(`The home-page plugin needs a "homePage" setting in ${settingsPath}; without it the snapshot task does nothing.`);
  }
  const freshness = settings.homePage.freshness ?? {};
  const unknown = Object.keys(freshness).filter((key) => !FRESHNESS_KEYS.includes(key));
  if (unknown.length > 0) throw new Error(`Unknown homePage.freshness settings: ${unknown.join(", ")}`);
  const threads = (settings.homePage.threads ?? {}) as Record<string, unknown>;
  const unknownThreads = Object.keys(threads).filter((key) => !THREADS_KEYS.includes(key));
  if (unknownThreads.length > 0) throw new Error(`Unknown homePage.threads settings: ${unknownThreads.join(", ")}`);
  if (threads.enabled !== undefined && typeof threads.enabled !== "boolean") throw new Error("homePage.threads.enabled must be true or false");
  return { ...freshness, threads: threads.enabled === true };
}

/** Request values win over the site's projection.json; both fall back to the defaults. */
export function resolveHomePageConfig(request: PluginRequest, options: PluginResolveOptions = {}): HomePageConfig {
  const settings: Record<string, unknown> = typeof request === "string" ? {} : request;
  const unknown = Object.keys(settings).filter((key) => !REQUEST_KEYS.includes(key));
  if (unknown.length > 0) throw new Error(`Unknown home-page plugin settings: ${unknown.join(", ")}`);
  const projected = readProjectionFreshness(options) ?? {};
  const debounce = settings.debounceSeconds ?? projected.debounceSeconds ?? DEFAULT_DEBOUNCE_SECONDS;
  const interval = "intervalHours" in settings ? settings.intervalHours : projected.intervalHours;
  const purge = projected.purge ?? false;
  if (typeof purge !== "boolean") throw new Error("homePage.freshness.purge must be true or false");
  return {
    debounceSeconds: wholeSeconds(debounce, "home-page debounceSeconds"),
    intervalHours: intervalHours(interval, "home-page intervalHours"),
    purge,
    threads: projected.threads === true,
  };
}
