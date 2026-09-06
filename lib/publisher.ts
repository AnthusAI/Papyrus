/**
 * Publisher plugin descriptor (spike).
 *
 * A "publisher" is the render pipeline that turns an `EditionContent` into a
 * readable site. It is orthogonal to `EditionPresentationFormat`
 * (`newspaper` | `blog` | `magazine`), which is a Pretext-internal concern.
 *
 * This module is a metadata-only registry for now: it describes the two known
 * publishers (Pretext, Markus) so config and dispatch shapes are concrete and
 * reviewable. It is NOT yet wired into `components/presentation-shell.tsx` or
 * any route. See `docs/pluggable-publishers.md` for the full design and the
 * phased wiring plan.
 *
 * Non-goals here: no dynamic plugin loading, no runtime registration.
 * Publishers are a compile-time registry mirroring `SITE_BRANDS`.
 */

export type PublisherId = "pretext" | "markus";

/**
 * Where the render geometry is owned.
 *
 * - `client-solver`: Pretext runs in the browser after hydration; the solver
 *   owns all geometry (`buildNewspaperLayout` / `layoutAllTextLines`).
 * - `static-html`: HTML fragments are produced at build time (e.g. by the
 *   Markus Python build step); the render shell only mounts them.
 */
export type PublisherRuntime = "client-solver" | "static-html";

export type Publisher = {
  id: PublisherId;
  runtime: PublisherRuntime;
  label: string;
  /** True when this publisher needs the Pretext client solver + EditionLayoutPlan. */
  requiresPretext: boolean;
  /** True when this publisher emits static HTML at build time. */
  staticOutput: boolean;
};

export const PUBLISHERS: Record<PublisherId, Publisher> = {
  pretext: {
    id: "pretext",
    runtime: "client-solver",
    label: "Pretext",
    requiresPretext: true,
    staticOutput: false,
  },
  markus: {
    id: "markus",
    runtime: "static-html",
    label: "Markus",
    requiresPretext: false,
    staticOutput: true,
  },
};

const DEFAULT_PUBLISHER_ID: PublisherId = "pretext";

function isPublisherId(value: string): value is PublisherId {
  return value === "pretext" || value === "markus";
}

/**
 * Resolve a publisher descriptor from a raw id string. Unknown / empty values
 * fall back to the default publisher (`pretext`) so existing pods are
 * unaffected. Call sites should pass `SITE_BRAND.publisher` once that field
 * exists; for now this is a pure helper.
 */
export function resolvePublisher(id: PublisherId | string | undefined): Publisher {
  if (id && isPublisherId(id)) return PUBLISHERS[id];
  return PUBLISHERS[DEFAULT_PUBLISHER_ID];
}
