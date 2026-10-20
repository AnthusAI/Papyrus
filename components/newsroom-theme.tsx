"use client";

import dynamic from "next/dynamic";
import type { KanbusThemeId } from "@kanbus/ui";
import "@kanbus/ui/styles/kanban.css";
import "@kanbus/ui/styles/themes/index.css";
import "./newsroom-theme.css";
import { getKanbusTheme, SITE_BRAND } from "../lib/site-brand";
import { useResolvedPapyrusTheme } from "./use-resolved-papyrus-theme";

/**
 * The Kanbus theme scope for the whole newsroom. The publication hard-codes its
 * theme (`SiteBrand.kanbusTheme`); only light/dark follows the editor's setting.
 * Spread onto the newsroom root and onto the portaled menus that render outside it.
 */
export function useNewsroomThemeAttributes() {
  const mode = useResolvedPapyrusTheme();
  // Same attributes as `kanbusThemeAttributes(theme, mode)` from @kanbus/ui; spelled out so server-side tests need no ESM-only import.
  return { "data-kanbus-theme": getKanbusTheme(SITE_BRAND), "data-color-mode": mode };
}

const THEME_FONTS: Record<KanbusThemeId, ReturnType<typeof dynamic>> = {
  "refined-newsprint": dynamic(() => import("./newsroom-theme-fonts/refined-newsprint")),
  "newspaper-gothic": dynamic(() => import("./newsroom-theme-fonts/newspaper-gothic")),
  "night-desk": dynamic(() => import("./newsroom-theme-fonts/night-desk")),
  "broadsheet-green": dynamic(() => import("./newsroom-theme-fonts/broadsheet-green")),
};

/** Loads the font files for the brand's theme only (the Playfair wordmark comes from the root layout). */
export function NewsroomThemeFonts() {
  const Fonts = THEME_FONTS[getKanbusTheme(SITE_BRAND)];
  return <Fonts />;
}
