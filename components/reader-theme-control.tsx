"use client";

import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  THEME_OPTIONS,
  applyReaderTheme,
  readLocalReaderSettings,
  saveReaderSettings,
  subscribeReaderSettingsChanges,
  type ReaderThemeSetting,
} from "./reader-settings";

type ReaderThemeControlProps = {
  className?: string;
};

const THEME_ICON_BY_VALUE: Record<ReaderThemeSetting, typeof MonitorIcon> = {
  system: MonitorIcon,
  light: SunIcon,
  dark: MoonIcon,
};

const THEME_LABEL_BY_VALUE: Record<ReaderThemeSetting, string> = {
  system: "Use system theme",
  light: "Use light theme",
  dark: "Use dark theme",
};

export function ReaderThemeControl({ className }: ReaderThemeControlProps) {
  const [theme, setTheme] = useState<ReaderThemeSetting>("system");
  const [pendingTheme, setPendingTheme] = useState<ReaderThemeSetting | null>(null);

  useEffect(() => {
    const localSettings = readLocalReaderSettings();
    setTheme(localSettings.theme);
    applyReaderTheme(localSettings.theme);
    return subscribeReaderSettingsChanges((settings) => {
      setTheme(settings.theme);
    });
  }, []);

  const updateTheme = useCallback(async (nextTheme: ReaderThemeSetting) => {
    const nextSettings = { ...readLocalReaderSettings(), theme: nextTheme };
    setTheme(nextTheme);
    setPendingTheme(nextTheme);
    applyReaderTheme(nextTheme);
    try {
      const resolution = await saveReaderSettings(nextSettings);
      setTheme(resolution.settings.theme);
    } catch {
      setTheme(nextTheme);
    } finally {
      setPendingTheme(null);
    }
  }, []);

  const rootClassName = className ? `reader-theme-control ${className}` : "reader-theme-control";

  return (
    <div aria-label="Theme mode" className={rootClassName} role="radiogroup">
      {THEME_OPTIONS.map((option) => {
        const selected = theme === option.value;
        const ThemeIcon = THEME_ICON_BY_VALUE[option.value];
        const label = THEME_LABEL_BY_VALUE[option.value];
        return (
          <button
            aria-checked={selected}
            aria-label={label}
            className="reader-theme-control__button"
            data-selected={selected ? "true" : "false"}
            disabled={pendingTheme !== null}
            key={option.value}
            onClick={() => void updateTheme(option.value)}
            role="radio"
            title={label}
            type="button"
          >
            <ThemeIcon aria-hidden="true" className="reader-theme-control__icon" focusable="false" />
          </button>
        );
      })}
    </div>
  );
}
