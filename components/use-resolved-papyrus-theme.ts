"use client";

import { useEffect, useState } from "react";
import type { ResolvedTheme } from "../lib/themed-image";

const SETTINGS_EVENT = "papyrus:settings-changed";

function readResolvedTheme(): ResolvedTheme {
  if (typeof document === "undefined" || typeof window === "undefined") return "light";
  const theme = document.documentElement.dataset.papyrusTheme;
  if (theme === "dark") return "dark";
  if (theme === "light") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useResolvedPapyrusTheme(): ResolvedTheme {
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("light");

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const refresh = () => setResolvedTheme(readResolvedTheme());
    refresh();
    media.addEventListener("change", refresh);
    window.addEventListener(SETTINGS_EVENT, refresh);
    window.addEventListener("storage", refresh);
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "attributes" && mutation.attributeName === "data-papyrus-theme") {
          refresh();
          break;
        }
      }
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-papyrus-theme"],
    });
    return () => {
      media.removeEventListener("change", refresh);
      window.removeEventListener(SETTINGS_EVENT, refresh);
      window.removeEventListener("storage", refresh);
      observer.disconnect();
    };
  }, []);

  return resolvedTheme;
}
