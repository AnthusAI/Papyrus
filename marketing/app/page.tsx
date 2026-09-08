/**
 * Design direction: editorial archaeology. Papyrus fiber, carbon ink, Nile
 * blue, reed green, and oxide-red marginalia turn the ancient writing surface
 * into a modern systems story. The asymmetric "living scroll" is the visual
 * anchor; motion is quiet, botanical, and CSS-only.
 */
import type { Metadata } from "next";
import { Faq } from "@/components/Faq";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { Hero } from "@/components/Hero";
import { Newsroom } from "@/components/Newsroom";
import { Ownership } from "@/components/Ownership";
import { Pricing } from "@/components/Pricing";
import { Waitlist } from "@/components/Waitlist";

export const metadata: Metadata = {
  title: "Open-source AI newsroom and publishing system",
  description: "Papyrus is an open-source, AI-assisted newsroom for a specific beat. Run it in your AWS account, manage it yourself, or hire Anthus for setup and operations—with no vendor lock-in.",
  keywords: ["open-source newsroom", "AI publishing system", "self-hosted CMS", "AI research agents", "AWS publishing"],
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    url: "/",
    title: "Papyrus — a newsroom with a long memory",
    description: "Build a source-grounded publication in your own AWS account. Keep the code, the data, and the freedom to run it your way.",
    siteName: "Papyrus",
  },
  twitter: {
    card: "summary_large_image",
    title: "Papyrus — a newsroom with a long memory",
    description: "Open-source, AI-assisted publishing with no vendor lock-in.",
  },
};

export default function HomePage() {
  return (
    <>
      <Header />
      <main id="main-content">
        <Hero />
        <Newsroom />
        <Ownership />
        <Pricing />
        <Faq />
        <Waitlist />
      </main>
      <Footer />
    </>
  );
}
