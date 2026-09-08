import Image from "next/image";
import { ArrowDownRight, ArrowUpRight, Check, GitFork, Quote } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const proof = [
  ["Open source", "Clone it. Change it. Keep it."],
  ["Your AWS", "Your account, data, and bill."],
  ["No permission", "Come to us—or leave—any time."],
];

export function Hero() {
  return (
    <section id="top" aria-labelledby="hero-title" className="relative overflow-hidden">
      <div className="papyrus-grid absolute inset-0 -z-10" />
      <div className="mx-auto grid max-w-[92rem] gap-14 px-5 pb-16 pt-14 sm:px-8 sm:pt-20 lg:grid-cols-[1.05fr_.95fr] lg:items-center lg:px-12 lg:pb-24 lg:pt-24">
        <div>
          <Badge variant="reed" className="animate-rise">Open-source, AI-assisted publishing</Badge>
          <h1 id="hero-title" className="mt-7 max-w-[54rem] animate-rise font-display text-[clamp(4.2rem,8.5vw,8.6rem)] font-medium leading-[.75] tracking-[-.065em] [animation-delay:90ms]">
            A newsroom with a <span className="relative italic text-oxide">long memory.<span aria-hidden="true" className="ink-stroke" /></span>
          </h1>
          <p className="mt-9 max-w-[43rem] animate-rise font-body text-lg font-medium leading-relaxed text-muted [animation-delay:190ms] sm:text-xl">
            Papyrus turns one subject worth following into a living publication. Research agents watch the beat, editors shape the coverage, and every story keeps its sources, concepts, and decisions attached.
          </p>
          <div className="mt-9 flex animate-rise flex-col gap-3 [animation-delay:290ms] sm:flex-row">
            <Button asChild size="lg"><a href="#waitlist">Join the wait-list <ArrowDownRight className="h-5 w-5" aria-hidden="true" /></a></Button>
            <Button asChild size="lg" variant="outline"><a href="https://p.apyr.us">Read the working demo <ArrowUpRight className="h-5 w-5" aria-hidden="true" /></a></Button>
          </div>
          <p className="mt-7 flex animate-rise items-center gap-2 font-mono text-[0.69rem] uppercase tracking-[.11em] text-muted [animation-delay:390ms]">
            <GitFork className="h-4 w-4 text-reed" aria-hidden="true" /> Start alone. Ask for help later. Or the other way around.
          </p>
        </div>

        <div className="relative mx-auto w-full max-w-[42rem] animate-rise [animation-delay:180ms]">
          <div aria-hidden="true" className="absolute -left-8 -top-10 h-52 w-40 animate-drift rounded-[50%] bg-nile/12 blur-3xl" />
          <div className="living-scroll relative overflow-hidden rounded-[1.5rem] border border-ink/20 bg-sheet p-3 shadow-sheet sm:p-5">
            <div className="mb-4 flex items-center justify-between border-b border-ink/15 pb-3 font-mono text-[.62rem] uppercase tracking-[.13em] text-muted">
              <span>Publication desk / current edition</span><span className="rounded-full bg-reed px-2.5 py-1 text-white">Live beat</span>
            </div>
            <div className="grid gap-3 sm:grid-cols-[.72fr_1.28fr]">
              <div className="space-y-3">
                <div className="rounded-xl bg-sand/65 p-4">
                  <p className="font-mono text-[.6rem] uppercase tracking-[.12em] text-muted">Sources watched</p>
                  <p className="mt-2 font-display text-4xl leading-none">34</p>
                  <div className="mt-4 space-y-2">
                    {["Primary record", "Research paper", "Local reporting"].map((source) => <div key={source} className="flex items-center gap-2 text-xs text-muted"><Check className="h-3.5 w-3.5 text-reed" />{source}</div>)}
                  </div>
                </div>
                <div className="rounded-xl border border-nile/25 bg-nile/10 p-4">
                  <p className="font-mono text-[.6rem] uppercase tracking-[.12em] text-nile">Topic map</p>
                  <div className="topic-map mt-4" aria-label="Connected publication topics">
                    <span>Policy</span><span>People</span><span>Capital</span><span>Evidence</span>
                  </div>
                </div>
              </div>
              <article className="relative rounded-xl border border-ink/15 bg-papyrus p-5 sm:p-6">
                <Image src="/papyrus-plant.png" alt="Papyrus plant pictogram" width={140} height={178} className="absolute -right-2 bottom-0 h-40 w-auto opacity-[.075]" priority />
                <div className="relative">
                  <p className="font-mono text-[.6rem] uppercase tracking-[.14em] text-oxide">Reporting packet 07</p>
                  <h2 className="mt-3 font-display text-[2.25rem] leading-[.9] tracking-[-.035em]">The story is more than the draft.</h2>
                  <p className="mt-4 text-sm leading-relaxed text-muted">Verified facts, source trail, open questions, risks, editorial angle, and a brief for the copy desk.</p>
                  <div className="mt-6 border-l-2 border-oxide pl-4">
                    <Quote className="h-4 w-4 text-oxide" aria-hidden="true" />
                    <p className="mt-2 font-display text-xl italic leading-tight">Keep the evidence beside the words.</p>
                  </div>
                  <div className="mt-7 flex items-center justify-between border-t border-ink/15 pt-3 font-mono text-[.58rem] uppercase tracking-[.1em] text-muted">
                    <span>Editor review</span><span>3 references</span><span>Edition 04</span>
                  </div>
                </div>
              </article>
            </div>
          </div>
        </div>
      </div>

      <div className="border-y border-ink/10 bg-reed text-white">
        <div className="mx-auto grid max-w-[92rem] divide-y divide-white/15 px-5 sm:px-8 lg:grid-cols-3 lg:divide-x lg:divide-y-0 lg:px-12">
          {proof.map(([value, label]) => (
            <div key={value} className="flex items-baseline gap-4 py-5 lg:px-6 first:lg:pl-0">
              <span className="font-display text-3xl italic">{value}</span>
              <span className="font-mono text-[.61rem] uppercase tracking-[.11em] text-white/70">{label}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
