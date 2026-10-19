import Link from "next/link";
import type { ItemStream } from "../lib/item-stream";
import { toPublicReaderPath } from "../lib/reader-base-path";
import { SITE_BRAND } from "../lib/site-brand";

/** The home of a publication without editions: a masthead, section filters and the newest items. */
export function ItemStreamView({ stream }: { stream: ItemStream }) {
  const homePath = toPublicReaderPath("/");
  const tagline = SITE_BRAND.mastheadTagline ?? null;

  return (
    <main className="presentation-page presentation-page--blog" data-presentation-engine="item-stream">
      <header className="presentation-header">
        <div className="presentation-header__copy-stack">
          <h1>
            <Link href={homePath}>{SITE_BRAND.mastheadTitle}</Link>
          </h1>
          <div className="presentation-header__meta">
            <span className="presentation-header__subtitle">{SITE_BRAND.mastheadSubtitle}</span>
          </div>
          {tagline ? <span className="presentation-header__tagline">{tagline}</span> : null}
        </div>
      </header>
      {stream.sections.length > 1 ? (
        <nav className="presentation-section-nav" aria-label="Sections">
          <Link href={homePath} aria-current={stream.activeSectionKey === null ? "page" : undefined}>
            All
          </Link>
          {stream.sections.map((section) => (
            <Link
              aria-current={stream.activeSectionKey === section.key ? "page" : undefined}
              href={`${homePath}?section=${encodeURIComponent(section.key)}`}
              key={section.key}
            >
              {section.label}
            </Link>
          ))}
        </nav>
      ) : null}
      {stream.items.length === 0 ? (
        <section className="item-stream-empty" data-item-stream-empty="true">
          <p>Nothing published yet</p>
        </section>
      ) : (
        <div className="blog-sections">
          {stream.items.map((item) => (
            <article className="presentation-item presentation-item--blog" data-item-id={item.slug} key={item.slug}>
              <div className="presentation-item__copy">
                <header className="presentation-item__header">
                  <p>{item.section ?? "General"}</p>
                  <h2>
                    <Link href={toPublicReaderPath(`/articles/${encodeURIComponent(item.slug)}`)}>{item.headline}</Link>
                  </h2>
                  {item.deck ? <span>{item.deck}</span> : null}
                </header>
              </div>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
