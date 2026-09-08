"use client";

import { FormEvent, useState } from "react";
import Image from "next/image";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function Waitlist() {
  const [previewMessage, setPreviewMessage] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPreviewMessage(true);
  }

  return (
    <section id="waitlist" aria-labelledby="waitlist-title" className="bg-oxide p-3 sm:p-5">
      <div className="relative overflow-hidden rounded-[1.7rem] bg-ink text-papyrus">
        <Image src="/papyrus-plant.png" alt="" width={620} height={790} className="pointer-events-none absolute -bottom-32 -right-16 h-[42rem] w-auto opacity-[.055] invert" />
        <div className="relative mx-auto grid max-w-[88rem] gap-14 px-5 py-20 sm:px-10 sm:py-24 lg:grid-cols-[1fr_.82fr] lg:items-center lg:px-16 lg:py-28">
          <div>
            <p className="font-mono text-[.65rem] font-semibold uppercase tracking-[.16em] text-sand">Early access / limited rollout</p>
            <h2 id="waitlist-title" className="mt-7 max-w-4xl font-display text-[clamp(4.2rem,8vw,8.5rem)] leading-[.75] tracking-[-.065em]">Bring us a beat worth <em className="text-sand">remembering.</em></h2>
            <p className="mt-8 max-w-2xl text-lg leading-relaxed text-papyrus/65 sm:text-xl">Tell us what you want to cover and how you imagine running it. Joining the wait-list does not commit you to a management plan—or to paying us anything.</p>
            <div className="mt-8 flex flex-wrap gap-x-7 gap-y-3 font-mono text-[.6rem] uppercase tracking-[.11em] text-papyrus/55">
              {["No credit card", "No sales trap", "No lock-in"].map((item) => <span key={item} className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-sand" aria-hidden="true" />{item}</span>)}
            </div>
          </div>

          <form onSubmit={handleSubmit} className="rounded-[1.4rem] bg-papyrus p-5 text-ink shadow-[8px_8px_0_var(--sand)] sm:p-7" aria-describedby="waitlist-note">
            <div className="grid gap-5">
              <label className="grid gap-2 font-mono text-[.64rem] font-semibold uppercase tracking-[.1em]" htmlFor="email">Work email<Input id="email" name="email" type="email" placeholder="editor@example.com" required /></label>
              <label className="grid gap-2 font-mono text-[.64rem] font-semibold uppercase tracking-[.1em]" htmlFor="beat">What would your publication cover?<Input id="beat" name="beat" placeholder="A place, an industry, a public institution…" required /></label>
              <label className="grid gap-2 font-mono text-[.64rem] font-semibold uppercase tracking-[.1em]" htmlFor="path">How do you want to begin?
                <select id="path" name="path" className="min-h-12 w-full rounded-xl border border-ink/20 bg-papyrus px-4 font-body text-base normal-case tracking-normal outline-none focus-visible:border-nile focus-visible:ring-4 focus-visible:ring-nile/15" defaultValue="exploring">
                  <option value="exploring">I am still exploring</option><option value="self">I want to run it myself</option><option value="setup">I want help setting it up</option><option value="managed">I want Anthus to manage it</option>
                </select>
              </label>
              <Button type="submit" size="lg" className="mt-1 w-full">Join the wait-list <ArrowRight className="h-5 w-5" aria-hidden="true" /></Button>
            </div>
            <p id="waitlist-note" className="mt-4 text-xs leading-relaxed text-muted">Design preview: the form is complete, but submissions are not connected yet. The wait-list service is the next implementation step.</p>
            {previewMessage ? <p role="status" className="mt-4 rounded-xl bg-reed px-4 py-3 text-sm font-bold text-white">The form design works. No information was sent or stored yet.</p> : null}
          </form>
        </div>
      </div>
    </section>
  );
}
