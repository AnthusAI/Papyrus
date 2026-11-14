"use client";
import { useEffect } from "react";
export function useTheme() {
  useEffect(() => {
    const q = new URLSearchParams(location.search).get("theme");
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = q ? q === "dark" : mq.matches;
      document.documentElement.dataset.theme = dark ? "dark" : "light";
      document.documentElement.dataset.colorScheme = dark ? "dark" : "light";
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
}
