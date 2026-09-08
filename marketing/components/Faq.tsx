import { Badge } from "@/components/ui/badge";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

const faqs = [
  ["What is Papyrus?", "Papyrus is an open-source publishing and newsroom system for a specific beat. It helps research agents and human editors monitor sources, maintain a publication-specific knowledge base, prepare reporting packets, review drafts, and publish editions."],
  ["Does Papyrus have to run in Anthus infrastructure?", "No. It is designed to run from your AWS account. Your content, data, file system, encrypted secrets, and infrastructure stay under your control."],
  ["Can I install it without paying Anthus?", "Yes. Clone the source, install it, change it, and run it yourself without our permission. There is no installation fee or monthly management fee when you do the work yourself."],
  ["Can I switch between self-managed and managed?", "Yes. That is central to the model. You can start on your own and ask us for help later, start managed and bring it in-house as your team grows, or ask for occasional professional services while remaining self-managed."],
  ["What does the $20/month managed option cover?", "It covers operational care for the standard Papyrus deployment, including availability, routine upgrades, security scanning, privacy safeguards, and general IT service management. AWS and model usage are still billed directly to you."],
  ["What does the $100 turn-key setup include?", "It is a one-time standard installation into your AWS account. Publication strategy, custom integrations, custom design, migration, and training are professional services scoped separately."],
  ["Is the demo at p.apyr.us the marketing site?", "No. papyrus.anth.us is the Papyrus product and sales site. p.apyr.us is a working content publication powered by Papyrus, so you can see the system's output."],
];

export function Faq() {
  return (
    <section id="faq" aria-labelledby="faq-title" className="section-rule bg-papyrus">
      <div className="mx-auto grid max-w-[92rem] gap-12 px-5 py-24 sm:px-8 sm:py-32 lg:grid-cols-[.65fr_1.35fr] lg:gap-20 lg:px-12">
        <div>
          <Badge variant="outline">Questions, answered</Badge>
          <h2 id="faq-title" className="mt-6 font-display text-[clamp(3.8rem,6vw,6.5rem)] leading-[.78] tracking-[-.055em]">Read the <em className="text-oxide">fine print.</em></h2>
          <p className="mt-7 max-w-sm text-lg leading-relaxed text-muted">The short version: it is your newsroom. We sell help, not dependence.</p>
        </div>
        <Accordion type="single" collapsible className="border-b border-ink/20">
          {faqs.map(([question, answer], index) => (
            <AccordionItem key={question} value={`faq-${index}`}>
              <AccordionTrigger>{question}</AccordionTrigger>
              <AccordionContent>{answer}</AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </div>
    </section>
  );
}
