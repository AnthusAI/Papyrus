import type { Metadata } from "next";
import { Playfair_Display, Plus_Jakarta_Sans } from "next/font/google";
import Script from "next/script";
import { AmplifyClientProvider } from "../components/amplify-client-provider";
import { PapyrusConsoleShell } from "../components/papyrus-console-shell";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SITE_BRAND, getPresentationChoices } from "../lib/site-brand";
import "./tailwind.css";
import "./globals.css";

const playfairDisplay = Playfair_Display({
  subsets: ["latin"],
  variable: "--font-serif",
});

const plusJakartaSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
});

const faviconVersion = "20260517-1";
const defaultTheme = "system";

export const metadata: Metadata = {
  title: SITE_BRAND.appTitle,
  description: SITE_BRAND.appDescription,
  icons: {
    icon: [
      { url: `/icon-light.png?v=${faviconVersion}`, type: "image/png" },
      { url: `/icon.png?v=${faviconVersion}`, type: "image/png" },
    ],
  },
};

const presentationChoices = getPresentationChoices();

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className="light light-theme"
      data-papyrus-theme={defaultTheme}
      data-site-brand={SITE_BRAND.id}
      data-default-presentation={SITE_BRAND.defaultPresentation}
      data-presentation-choices={presentationChoices.join(",")}
      {...(SITE_BRAND.forcedPresentation ? { "data-forced-presentation": SITE_BRAND.forcedPresentation } : {})}
      suppressHydrationWarning
    >
      <body className={`${playfairDisplay.variable} ${plusJakartaSans.variable}`}>
        <Script id="papyrus-favicon-color-scheme" strategy="beforeInteractive">
          {`(() => {
  const version = "${faviconVersion}";
  const lightHref = "/icon-light.png?v=" + version;
  const darkHref = "/icon-dark.png?v=" + version;
  const settingsStorageKey = "papyrus:reader-settings";
  const defaultTheme = "${defaultTheme}";

  const getLink = () => {
    const existingTagged = document.querySelector('link[rel="icon"][data-papyrus-theme-icon="true"]');
    if (existingTagged) return existingTagged;

    const existingPng = document.querySelector('link[rel="icon"][type="image/png"]');
    if (existingPng) {
      existingPng.setAttribute("data-papyrus-theme-icon", "true");
      return existingPng;
    }

    const link = document.createElement("link");
    link.rel = "icon";
    link.type = "image/png";
    link.setAttribute("data-papyrus-theme-icon", "true");
    document.head.appendChild(link);
    return link;
  };

  const iconLink = getLink();
  const readTheme = () => {
    try {
      const stored = window.localStorage.getItem(settingsStorageKey);
      const parsed = stored ? JSON.parse(stored) : null;
      return parsed && (parsed.theme === "light" || parsed.theme === "dark" || parsed.theme === "system")
        ? parsed.theme
        : defaultTheme;
    } catch {
      return defaultTheme;
    }
  };
  const isDarkTheme = (theme) => theme === "dark" || (theme === "system" && media.matches);
  const applyThemeClass = (theme) => {
    const isDark = isDarkTheme(theme);
    document.documentElement.classList.toggle("dark", isDark);
    document.documentElement.classList.toggle("dark-theme", isDark);
    document.documentElement.classList.toggle("light", !isDark);
    document.documentElement.classList.toggle("light-theme", !isDark);
    return isDark;
  };
  const apply = () => {
    const theme = readTheme();
    document.documentElement.dataset.papyrusTheme = theme;
    const isDark = applyThemeClass(theme);
    const nextHref = isDark ? darkHref : lightHref;
    if (iconLink.getAttribute("href") !== nextHref) {
      iconLink.setAttribute("href", nextHref);
    }
  };

  const media = window.matchMedia("(prefers-color-scheme: dark)");
  apply();

  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", apply);
  } else if (typeof media.addListener === "function") {
    media.addListener(apply);
  }
  window.addEventListener("storage", (event) => {
    if (event.key === settingsStorageKey) apply();
  });
  window.addEventListener("papyrus:settings-changed", apply);
})();`}
        </Script>
        <AmplifyClientProvider>
          <TooltipProvider>
            <PapyrusConsoleShell>{children}</PapyrusConsoleShell>
          </TooltipProvider>
        </AmplifyClientProvider>
      </body>
    </html>
  );
}
