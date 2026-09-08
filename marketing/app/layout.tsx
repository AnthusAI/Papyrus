import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://papyrus.anth.us"),
  title: {
    default: "Papyrus",
    template: "%s | Papyrus",
  },
  description: "Papyrus is a publishing system for thoughtful, human-steered publication.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
