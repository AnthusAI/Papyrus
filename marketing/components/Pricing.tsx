import { Check, Minus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const plans = [
  {
    eyebrow: "Do everything yourself",
    title: "Independent",
    setup: "$0",
    monthly: "$0",
    accent: false,
    features: ["Self-install from source", "Run it in your AWS account", "Community updates", "No fee to Anthus"],
  },
  {
    eyebrow: "We get you running",
    title: "Turn-key",
    setup: "$100",
    monthly: "$0",
    accent: false,
    features: ["One-time standard installation", "Your AWS account", "Then you operate it", "Optional help later"],
  },
  {
    eyebrow: "We keep it running",
    title: "Managed",
    setup: "$0",
    monthly: "$20",
    accent: true,
    features: ["You handle initial installation", "Managed standard deployment", "Upgrades and operational care", "Take it in-house any time"],
  },
  {
    eyebrow: "We handle both",
    title: "Turn-key + managed",
    setup: "$100",
    monthly: "$20",
    accent: false,
    features: ["Standard installation", "Ongoing management", "Your AWS account and data", "No long-term commitment"],
  },
];

export function Pricing() {
  return (
    <section id="pricing" aria-labelledby="pricing-title" className="section-rule bg-sand/70">
      <div className="mx-auto max-w-[92rem] px-5 py-24 sm:px-8 sm:py-32 lg:px-12">
        <div className="flex flex-col justify-between gap-8 lg:flex-row lg:items-end">
          <div>
            <Badge variant="outline">Simple pricing</Badge>
            <h2 id="pricing-title" className="mt-6 max-w-4xl font-display text-[clamp(3.8rem,7vw,7.5rem)] leading-[.76] tracking-[-.06em]">Pay for help. <em className="text-oxide">Not permission.</em></h2>
          </div>
          <p className="max-w-md font-body text-lg leading-relaxed text-muted">Installation and management are two independent choices. Both fees are optional. Change the arrangement as your publication changes.</p>
        </div>

        <div className="mt-14 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {plans.map((plan) => (
            <article key={plan.title} className={`relative flex min-h-[31rem] flex-col rounded-[1.5rem] border p-6 transition duration-300 hover:-translate-y-1 hover:shadow-sheet ${plan.accent ? "border-ink bg-reed text-white" : "border-ink/20 bg-papyrus"}`}>
              {plan.accent ? <span className="absolute right-5 top-5 rounded-full bg-sand px-3 py-1 font-mono text-[.57rem] font-bold uppercase tracking-[.1em] text-ink">Popular handoff</span> : null}
              <p className={`font-mono text-[.61rem] uppercase tracking-[.12em] ${plan.accent ? "text-white/60" : "text-muted"}`}>{plan.eyebrow}</p>
              <h3 className="mt-4 min-h-[4.5rem] font-display text-[2.45rem] leading-[.86] tracking-[-.035em]">{plan.title}</h3>
              <div className={`mt-7 grid grid-cols-2 border-y py-5 ${plan.accent ? "border-white/20" : "border-ink/15"}`}>
                <div><p className={`font-mono text-[.57rem] uppercase tracking-[.1em] ${plan.accent ? "text-white/55" : "text-muted"}`}>Once</p><p className="mt-1 font-display text-3xl">{plan.setup}</p></div>
                <div className={`border-l pl-5 ${plan.accent ? "border-white/20" : "border-ink/15"}`}><p className={`font-mono text-[.57rem] uppercase tracking-[.1em] ${plan.accent ? "text-white/55" : "text-muted"}`}>Monthly</p><p className="mt-1 font-display text-3xl">{plan.monthly}</p></div>
              </div>
              <ul className="mt-6 flex-1 space-y-3 text-sm">
                {plan.features.map((feature) => <li key={feature} className="flex gap-2.5"><Check className={`mt-0.5 h-4 w-4 shrink-0 ${plan.accent ? "text-sand" : "text-reed"}`} aria-hidden="true" />{feature}</li>)}
              </ul>
              <Button asChild variant={plan.accent ? "default" : "ink"} className="mt-7 w-full"><a href="#waitlist">Choose later—join now</a></Button>
            </article>
          ))}
        </div>

        <div className="mt-6 grid gap-4 rounded-2xl border border-ink/15 bg-papyrus p-6 sm:grid-cols-3 sm:p-8">
          <div><p className="font-mono text-[.6rem] uppercase tracking-[.11em] text-muted">Always yours</p><p className="mt-2 font-display text-2xl">Account, content, source</p></div>
          <div><p className="font-mono text-[.6rem] uppercase tracking-[.11em] text-muted">Billed directly to you</p><p className="mt-2 font-display text-2xl">AWS + model usage</p></div>
          <div><p className="font-mono text-[.6rem] uppercase tracking-[.11em] text-muted">Beyond the standard setup</p><p className="mt-2 font-display text-2xl">Training + custom work</p></div>
        </div>
        <p className="mt-5 flex items-center gap-2 text-sm leading-relaxed text-muted"><Minus className="h-4 w-4 shrink-0 text-oxide" aria-hidden="true" />Managed service is for the standard Papyrus deployment. Custom integrations, publication design, training, and editorial workflow consulting are available separately from Anthus AI Solutions.</p>
      </div>
    </section>
  );
}
