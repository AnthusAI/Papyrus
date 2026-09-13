import type { EditionLayoutPlan } from "./layout-plan";

export type PretextLayout = "newsprint" | "blog" | "magazine";

export type PretextRendererConfig = {
  kind: "pretext";
  layout: PretextLayout;
  layoutPlan: EditionLayoutPlan;
};

export type MarkusRendererConfig = {
  kind: "markus";
  theme: string;
};

export type RendererConfig = PretextRendererConfig | MarkusRendererConfig;

/** Sibling deploy target — type-only in PPY-eca592; not a required SiteBrand field. */
export type HostingConfig =
  | { kind: "amplify-ssr" }
  | { kind: "amplify-static" };

export function isPretextRendererConfig(config: RendererConfig): config is PretextRendererConfig {
  return config.kind === "pretext";
}

export function isMarkusRendererConfig(config: RendererConfig): config is MarkusRendererConfig {
  return config.kind === "markus";
}

export function assertPretextRendererConfig(config: RendererConfig): PretextRendererConfig {
  if (config.kind !== "pretext") {
    throw new Error(
      `Site renderer is "${config.kind}"; Next.js reader routes require kind "pretext". `
      + "Markus sites use `poetry run papyrus renderers markus-build` and static hosting.",
    );
  }
  return config;
}

export class MarkusSiteRendererError extends Error {
  constructor(theme: string, siteBrandId = "unknown") {
    super(
      `Site brand "${siteBrandId}" uses Markus renderer (theme "${theme}"). `
      + "Next.js reader routes are not available. "
      + "Build with `poetry run papyrus renderers markus-build` and serve `web/dist/` statically.",
    );
    this.name = "MarkusSiteRendererError";
  }
}
