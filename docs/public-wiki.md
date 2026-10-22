# Public wiki

A read-only wiki of the entities and topics a publication has accepted. Every page is an ordinary published Item of type `wiki_page` in a wiki section, so the projector gives it a listing page, a sitemap entry, a Markdown twin and an `llms.txt` line like any other page. Counts, trend lines and neighbours are not copied into the page: the page asks for them with knowledge blocks, and they are drawn from the [knowledge snapshot](knowledge-snapshot.md) when the site is projected.

Status: Beta. Public editing, history, discussion and contributor counts are out of scope. A reader can only suggest an edit.

## The rules

- **Nothing is public until it is published.** `wiki sync` writes drafts and never publishes. A page with generated text that nobody accepted has no review stamp, and a publish without a stamp is refused.
- **Honest labels.** Today an AI agent accepts entities and publishes the pages, so a page says `Draft, not yet reviewed. Edited by AI on 2026-10-22`: text an AI edited is a draft until a person reviews it, and never reads as attested. A page a person reviewed says `Reviewed by Ada Reader on 2026-10-22` (or `Reviewed by an editor on 2026-10-22` with no name). A published page that somehow has no valid stamp says `Draft, not yet reviewed`. The footer links the entity data as `Graph JSON`.
- **The node is the source of truth.** The page text comes from the accepted entity. Change the entity (`papyrus knowledge entities describe`, `rename`), run the sync, publish the revision.
- **No language model runs here.** The sync uses the entity's existing description when it has been accepted (state `reviewed`, or `ai_edited` by the AI editor). A description that is only a draft is left out and reported as a warning. An entity with no usable description gets one factual line: its name, its kind and its other names.

## Set up a site

`projection.json`:

```json
{
  "urls": { "sections": { "wiki": { "label": "Wiki" }, "topics": { "label": "Topics" } } },
  "listings": { "types": ["article", "wiki_page"] },
  "components": { "itemPagesDependOn": ["posts"] },
  "seo": { "jsonLdTypes": { "wiki_page": "WebPage" } },
  "forms": {
    "suggest-edit": {
      "title": "Suggest an edit",
      "endpoint": "https://<id>.lambda-url.us-east-1.on.aws/",
      "submitLabel": "Send suggestion",
      "fields": [
        { "name": "message", "label": "What should change?", "type": "textarea", "required": true },
        { "name": "email", "label": "Your email (optional)", "type": "email" }
      ]
    }
  },
  "wiki": { "suggestForm": "suggest-edit" }
}
```

- `urls.sections.wiki` and `urls.sections.topics` give the entity pages and the topic pages their own sections and listing pages. The section names are the `--section` and `--topics-section` of the sync (defaults `wiki` and `topics`).
- `urls.sections.wiki.pageSize` sets how many wiki pages one listing page shows (default: the site's `listings.pageSize`, 10), like any section: `"wiki": { "label": "Wiki", "pageSize": 48 }`. The listing continues at `/wiki/page/2/` and so on.
- `listings.types` must include `wiki_page`, or the pages exist but no listing, tag page or feed selects them.
- `components.itemPagesDependOn` is needed only when topic pages list items (see "Topic pages"): name the sections they list. An item page re-renders when the entries it depends on change, so a listing in a topic page without it is a build error, not a stale page.
- `seo.jsonLdTypes` is optional; without it a listed type reports `Article` structured data.
- `wiki.types` (default `["wiki_page"]`) is the set of entry types that carry the stamp and the footer. `wiki.dataLink` (default true) turns the link to the entity's JSON on or off. `wiki.suggestForm` names a `forms` entry; without it the footer shows only the update date and the data link.
- The knowledge snapshot must be written for the site (`papyrus knowledge snapshot`), with `--entity-href '/wiki/{slug}/'` so entity chips link to the pages. `{slug}` is the entity key with `--` folded to `-`, which is the page's slug (`maker--acme-loom` lives at `/wiki/maker-acme-loom/`).
- A site whose hooks replace `main` or `page_body` places the parts itself: `page.wiki_stamp` goes above the text and `page.wiki_footer` below it.

## Commands

All commands act on the backend the CLI is configured for. Both are dry runs until you pass `--apply`.

### `papyrus knowledge wiki sync`

```bash
papyrus knowledge wiki sync [--section wiki] [--apply] [--json]
papyrus knowledge wiki sync --beats-category-set <set id> [--topics-section topics] [--subtopic-min-items 30] [--items-per-topic 20] [--topic-sections posts,essays] [--topics-url '/topics/{slug}/'] --apply
papyrus knowledge wiki sync --beats-config web/scoring.json --apply
```

For each accepted entity it creates or updates a draft page in the wiki section. The Item id is `item-<section>-<slug>`; the slug is the entity key with `--` folded to `-`. Rejected and merely generated entities get no page.

What happens to a page that already exists:

| Situation | Result |
| --- | --- |
| No page yet | A new draft Item. |
| A draft page whose entity changed | The draft is updated in place. |
| A published page whose entity changed | A pending revision: a new draft version of the same lineage (`<lineage>-v2`), marked current. The live page is untouched until the revision is published. A second change updates that draft rather than adding versions. |
| Nothing changed | Nothing is written. |
| An entity that is no longer accepted | A warning. The page is left as it is; unpublish it by hand if it should go. |

The sync removes the `review` stamp from any text it writes, so changed text can never keep the stamp of the text it replaced.

#### Front matter of an entity page

| Field | Meaning |
| --- | --- |
| `title` | The entity name. |
| `entityKey` | The public entity key (`kind--name`). Matches `_data/knowledge/entities/<key>.json`. |
| `kind` | The entity kind. |
| `entityAliases` | Other names, from the node. Named `entityAliases` so it cannot be mistaken for the redirect `aliases` of a directory-sourced item. |
| `beat` | The beat that holds most of the entity's items, when a beat source is given. |
| `related` | Keys of the accepted entities it has an editor-confirmed relation with. |
| `description` | The accepted description, when there is one (used for the page summary). |
| `pin`, `annotations` | Optional, set by an editor and kept by the sync. `annotations: [{date: 2026-09-24, label: Launch}]` marks a week on the trend chart (the first one is used). |
| `superseded_by` | Optional, set by an editor and kept by the sync. See "Stamps". |
| `review`, `updated` | Written by `wiki publish`. See "Stamps". |

The body is the name as a heading, the description (or the factual line), then `::include{kind="block" name="knowledge-entity" key=... part="trend"}`, `part="neighbourhood"` and `part="related"` under a "Related coverage" heading. The Markdown twin keeps those lines as written.

### Topic pages

With `--beats-category-set` (the accepted root categories of a category set) or `--beats-config` (a `topics` mapping, as for the snapshot), the same command syncs a page per beat into the topics section. A beat page has its category description (when it has one) and a listing of the beat's items:

```
::include{kind="listing" sections="posts" tags="weaving,Weaving" count="20"}
```

The listing selects by front-matter tag: the beat key and the beat name. Items that belong to a beat only through an accepted cluster, and carry neither tag, are counted for the beat but not listed. `--topic-sections` narrows the listing to the sections that hold the articles, and `components.itemPagesDependOn` must name the same sections.

A beat with fewer than 30 published items (`--subtopic-min-items`) shows no subtopic list and gets no subtopic pages. At 30 or more, its accepted child categories that have items each get a page (`<beat>-<subtopic>`, with `topicKind: subtopic` and `parentTopic`), and the beat page lists them under "Subtopics". `--topics-url` is the template of those links; it must match the site's `urls.style` (`/topics/{slug}/` for `directory`, `/topics/{slug}.html` for `html`). Turn topic pages off with `--no-topics`.

Front matter: `title`, `topicKey`, `topicKind` (`beat` or `subtopic`), `parentTopic`, `description`, and the editor-owned `pin`, `annotations`, `superseded_by`.

### `papyrus knowledge wiki publish`

```bash
papyrus knowledge wiki publish --all-drafts --actor ai --apply
papyrus knowledge wiki publish maker-acme-loom --actor human --actor-name "Ada Reader" --apply
papyrus knowledge wiki publish item-wiki-maker-acme-loom --actor human --apply
```

The target is an item id or a slug (`--section` disambiguates), or `--all-drafts`: every wiki page whose current version is not what is live. `--actor ai` says an AI agent edited the page; `--actor human` says a person reviewed it, with `--actor-name` for their name (never an email address). `--on YYYY-MM-DD` sets the date (default today, UTC). The command writes the stamp into the front matter and publishes through the normal publish path, so the usual project and rebuild triggers run (`--no-trigger` skips them).

Naming a page explicitly always re-stamps it, which is how a person takes over from the AI: publish it again with `--actor human`.

## Stamps

Front matter, written by `wiki publish`:

```yaml
review: {actor: ai, name: null, on: 2026-10-22}
updated: 2026-10-22
```

or `review: {actor: human, name: Ada Reader, on: 2026-10-22}`. The checker is plain code, with no model in it: `publish_item` refuses an Item of type `wiki_page` unless `review.actor` is `ai` or `human`, `review.on` is a date and `review.name` is null or a name without an address (error code `wiki-stamp`). It applies to every publish path of the CLI, not only `wiki publish`. This includes the editors' own concept-wiki items.

On the page, the stamp sits above the text, with a mark as well as words (`✎` AI, `✓` person, `○` unreviewed). The Markdown twin carries the same line.

A superseded page: set `superseded_by: /wiki/new-page/` (a site path or an https URL) in its front matter and publish it again. The page then shows `This page has been superseded. See the replacement page`, linking the replacement, and its twin says so too. The old page stays reachable; nothing is deleted.

## Suggest an edit

When `wiki.suggestForm` is set, the footer of every wiki page shows `Updated <date>`, a link to `/_data/knowledge/entities/<key>.json` (only when the snapshot has that entity), and the form behind a "Suggest an edit" disclosure. The form is a normal public form: it posts to the public form endpoint ([public-forms.md](public-forms.md)) with `?form=suggest-edit` and the page path, and the endpoint stores a private Message. Triage it with `papyrus messages list --kind form_submission`. The public page does not change when a suggestion is sent; an editor makes the change on the entity and publishes a revision. Without an endpoint, the form says it is not open yet and cannot be submitted.

## Typical run

```bash
papyrus knowledge publish-run --run-dir ./run --apply        # entities from a workstation run
papyrus knowledge entities accept --key maker--acme-loom
papyrus knowledge entities describe --key maker--acme-loom --text "..." --reviewed
papyrus knowledge wiki sync --beats-category-set <set id> --topic-sections posts --apply
papyrus knowledge wiki publish --all-drafts --actor ai --apply
papyrus knowledge snapshot --site-bucket <bucket> --entity-href '/wiki/{slug}/' --reproject
```

Code: `src/papyrus_content/knowledge_wiki/` (sync and commands), `src/papyrus_content/wiki_stamp.py` (the stamp and its checker), `src/papyrus_content/projection/standard/wiki.py` (the stamp, notice and footer on the page). Tests: `procedures/newsroom/tests/test_knowledge_wiki.py`.
