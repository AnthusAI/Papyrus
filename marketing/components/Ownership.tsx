import { ArrowLeftRight, Download, HeartHandshake, ShieldCheck } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const paths = [
  { from: "Run it yourself", to: "Bring us in when it grows", note: "No migration. No rebuild." },
  { from: "Let us manage it", to: "Take it in-house later", note: "Same code. Same AWS account." },
  { from: "Mix and match", to: "Change your mind any time", note: "Help is a service, not a gate." },
];

export function Ownership() {
  return (
    <section id="ownership" aria-labelledby="ownership-title" className="overflow-hidden bg-ink text-papyrus">
      <div className="mx-auto max-w-[92rem] px-5 py-24 sm:px-8 sm:py-32 lg:px-12">
        <div className="grid items-start gap-16 lg:grid-cols-[.9fr_1.1fr] lg:gap-24">
          <div>
            <Badge variant="nile">No vendor lock-in</Badge>
            <h2 id="ownership-title" className="mt-7 font-display text-[clamp(4rem,7vw,7.4rem)] leading-[.76] tracking-[-.06em]">The door stays <em className="text-sand">open.</em></h2>
            <p className="mt-8 max-w-xl font-body text-lg leading-relaxed text-papyrus/70 sm:text-xl">Papyrus runs from your AWS account. The source is available. Your data stays yours. Clone it and run it without asking us—or hire us for exactly as long as we are useful.</p>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <Button asChild size="lg"><a href="https://github.com/AnthusAI/Papyrus"><Download className="h-5 w-5" aria-hidden="true" />Clone Papyrus</a></Button>
              <Button asChild size="lg" variant="outline" className="border-papyrus/25 bg-papyrus/10 text-papyrus hover:bg-papyrus hover:text-ink"><a href="#pricing">See support options</a></Button>
            </div>
          </div>
          <div className="space-y-3">
            {paths.map((path, index) => (
              <article key={path.from} className="group grid gap-4 rounded-2xl border border-papyrus/15 bg-papyrus/[.055] p-5 transition hover:border-sand/55 hover:bg-papyrus/[.08] sm:grid-cols-[1fr_auto_1fr] sm:items-center sm:p-7">
                <div><p className="font-mono text-[.59rem] uppercase tracking-[.12em] text-papyrus/45">Start here {String(index + 1).padStart(2, "0")}</p><h3 className="mt-2 font-display text-2xl leading-none">{path.from}</h3></div>
                <ArrowLeftRight className="h-6 w-6 text-oxide transition group-hover:scale-110" aria-hidden="true" />
                <div><h3 className="font-display text-2xl leading-none">{path.to}</h3><p className="mt-2 font-mono text-[.59rem] uppercase tracking-[.1em] text-sand/70">{path.note}</p></div>
              </article>
            ))}
            <div className="mt-8 flex items-start gap-4 rounded-2xl bg-sand p-6 text-ink">
              <Avatar><AvatarFallback>A</AvatarFallback></Avatar>
              <div>
                <div className="flex items-center gap-2"><HeartHandshake className="h-4 w-4 text-oxide" aria-hidden="true" /><p className="font-mono text-[.62rem] font-semibold uppercase tracking-[.12em]">The open-source compact</p></div>
                <p className="mt-3 font-display text-2xl italic leading-tight">Use it freely. If it helps you, remember us when you need help—and send back improvements others might use.</p>
                <p className="mt-3 flex items-center gap-2 text-sm text-muted"><ShieldCheck className="h-4 w-4 text-reed" aria-hidden="true" />Stewarded by Anthus AI Solutions</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
