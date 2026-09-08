import Image from "next/image";

const demoSiteUrl = "https://p.apyr.us";

export default function HomePage() {
  return (
    <main>
      <section aria-labelledby="page-title" className="foundation">
        <div className="wordmark" aria-label="Papyrus">
          <Image src="/papyrus-plant.png" alt="Papyrus plant" width={38} height={48} priority />
          <span>Papyrus</span>
        </div>

        <p className="eyebrow">The publishing system</p>
        <h1 id="page-title">A place to begin.</h1>
        <p className="summary">
          Papyrus is building a calmer way to shape research, editorial judgment, and publishing into work people want to read.
        </p>
        <p className="note">
          This is the public home for Papyrus. The live publication demo remains at{" "}
          <a href={demoSiteUrl}>p.apyr.us</a>.
        </p>
      </section>
    </main>
  );
}
