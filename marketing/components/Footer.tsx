import { ArrowUpRight, Github } from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { Wordmark } from "@/components/Wordmark";

export function Footer() {
  return (
    <footer className="bg-ink px-5 pb-10 pt-14 text-papyrus sm:px-8 lg:px-12">
      <div className="mx-auto max-w-[88rem]">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-[1.4fr_.6fr_.6fr]">
          <div><Wordmark inverse /><p className="mt-5 max-w-sm text-sm leading-relaxed text-papyrus/55">An open-source newsroom system, stewarded by Anthus AI Solutions.</p></div>
          <div><p className="font-mono text-[.61rem] uppercase tracking-[.12em] text-papyrus/40">Explore</p><ul className="mt-4 space-y-3 text-sm"><li><a className="footer-link" href="https://p.apyr.us">Working demo <ArrowUpRight className="h-3.5 w-3.5" /></a></li><li><a className="footer-link" href="#pricing">Pricing</a></li><li><a className="footer-link" href="#faq">FAQ</a></li></ul></div>
          <div><p className="font-mono text-[.61rem] uppercase tracking-[.12em] text-papyrus/40">Open work</p><ul className="mt-4 space-y-3 text-sm"><li><a className="footer-link" href="https://github.com/AnthusAI/Papyrus"><Github className="h-3.5 w-3.5" />GitHub</a></li><li><a className="footer-link" href="https://anth.us">Anthus AI Solutions <ArrowUpRight className="h-3.5 w-3.5" /></a></li></ul></div>
        </div>
        <Separator className="my-9 text-papyrus" />
        <div className="flex flex-col gap-3 font-mono text-[.58rem] uppercase tracking-[.1em] text-papyrus/35 sm:flex-row sm:justify-between"><p>© {new Date().getFullYear()} Anthus AI Solutions</p><p>Made to be taken with you.</p></div>
      </div>
    </footer>
  );
}
