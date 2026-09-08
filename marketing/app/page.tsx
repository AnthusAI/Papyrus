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

        <p className="eyebrow">A newsroom system for a specific beat</p>
        <h1 id="page-title">Follow the story, not the feed.</h1>
        <p className="summary">
          Papyrus turns a subject you care about into a publication that can keep learning: its sources, its vocabulary, its open questions, and its editorial judgment.
        </p>

        <div className="principles">
          <section>
            <h2>A beat is configuration, not code.</h2>
            <p>
              Start with any subject worth watching closely. Define its sources, the categories that matter, and the sections your readers need. The publication changes shape without rebuilding the software.
            </p>
          </section>
          <section>
            <h2>Keep the evidence with the story.</h2>
            <p>
              Papyrus manages the newsroom around an article: references, a reviewed topic map, concepts and their relationships, assignments, drafts, editions, and the decisions that connect them.
            </p>
          </section>
          <section>
            <h2>Give automation an editor.</h2>
            <p>
              Research agents watch the beat and prepare source-grounded reporting packets. Editors steer coverage, choose what becomes copy, and review the work before it reaches readers.
            </p>
          </section>
        </div>

        <p className="note">
          See the system in a working publication at <a href={demoSiteUrl}>p.apyr.us</a>.
        </p>
      </section>
    </main>
  );
}
