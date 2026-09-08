import { Binoculars, BookOpenText, Network, PenLine } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const stages = [
  {
    number: "I",
    icon: Binoculars,
    title: "Watch the beat",
    text: "Research agents monitor the sources you choose and surface developments that belong in your publication—not whatever happens to be loud today.",
  },
  {
    number: "II",
    icon: Network,
    title: "Build the memory",
    text: "References, people, organizations, claims, and relationships become a reviewed knowledge base that gets more useful with every reporting cycle.",
  },
  {
    number: "III",
    icon: PenLine,
    title: "Exercise judgment",
    text: "Editors choose the angle, open assignments, challenge the evidence, and decide what is ready. Automation works for the desk, not instead of it.",
  },
  {
    number: "IV",
    icon: BookOpenText,
    title: "Publish an edition",
    text: "Turn reporting packets into reviewed copy, assemble sections and editions, and publish a site whose shape follows the subject you cover.",
  },
];

export function Newsroom() {
  return (
    <section id="newsroom" aria-labelledby="newsroom-title" className="section-rule bg-papyrus">
      <div className="mx-auto max-w-[92rem] px-5 py-24 sm:px-8 sm:py-32 lg:px-12">
        <div className="grid gap-10 lg:grid-cols-[.72fr_1.28fr] lg:gap-20">
          <div className="lg:sticky lg:top-28 lg:self-start">
            <Badge variant="outline">The newsroom system</Badge>
            <h2 id="newsroom-title" className="mt-6 max-w-lg font-display text-[clamp(3.5rem,6vw,6.4rem)] leading-[.8] tracking-[-.055em]">From signal to <em className="text-nile">record.</em></h2>
            <p className="mt-7 max-w-md font-body text-lg leading-relaxed text-muted">A feed forgets. Papyrus accumulates context, preserves provenance, and makes editorial decisions visible.</p>
          </div>
          <div className="relative grid gap-4 sm:grid-cols-2">
            <div aria-hidden="true" className="story-thread absolute bottom-10 left-1/2 top-10 hidden w-px bg-oxide/30 sm:block" />
            {stages.map((stage, index) => {
              const Icon = stage.icon;
              return (
                <Card key={stage.title} className={`relative overflow-hidden transition duration-300 hover:-translate-y-1 hover:shadow-sheet ${index % 2 ? "sm:translate-y-14" : ""}`}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <span className="font-display text-5xl italic text-oxide/35">{stage.number}</span>
                      <span className="grid h-12 w-12 place-items-center rounded-full bg-reed text-white"><Icon className="h-5 w-5" aria-hidden="true" /></span>
                    </div>
                    <CardTitle className="mt-7">{stage.title}</CardTitle>
                  </CardHeader>
                  <CardContent><CardDescription>{stage.text}</CardDescription></CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
