import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        papyrus: "var(--papyrus)",
        sheet: "var(--sheet)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        reed: "var(--reed)",
        nile: "var(--nile)",
        oxide: "var(--oxide)",
        sand: "var(--sand)",
      },
      fontFamily: {
        display: ["var(--font-display)"],
        body: ["var(--font-body)"],
        mono: ["var(--font-mono)"],
      },
      boxShadow: {
        ink: "6px 6px 0 var(--ink)",
        sheet: "0 24px 80px rgb(49 39 20 / 0.16)",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(24px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        grow: {
          "0%": { transform: "scaleY(.75)", opacity: ".55" },
          "100%": { transform: "scaleY(1)", opacity: "1" },
        },
        drift: {
          "0%, 100%": { transform: "translate3d(0,0,0) rotate(-1deg)" },
          "50%": { transform: "translate3d(0,-8px,0) rotate(1deg)" },
        },
        accordionDown: {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        accordionUp: {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        rise: "rise 700ms cubic-bezier(.2,.75,.2,1) both",
        grow: "grow 1000ms cubic-bezier(.2,.75,.2,1) both",
        drift: "drift 9s ease-in-out infinite",
        "accordion-down": "accordionDown 220ms ease-out",
        "accordion-up": "accordionUp 220ms ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
