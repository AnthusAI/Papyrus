# Four-lens Story review

Before a Story is published it is looked at four ways: as people read it, as AI reader agents read it, as search crawlers read it and as a social preview shows it. The four lenses are defined once, in `src/papyrus_content/audience_lenses.py`, the way the [Story procedure](story-procedure.md) is defined once in `newsroom_process.py`. Everything below is generated from that definition, so there is no second copy. Design and the questions behind it: PPY-59c772.

## What this is for

- **The lens steps are mainly for agents.** An agent does them before a person reviews the Story, so obvious problems are fixed before any human time is spent. An agent may finish a lens step, and it is recorded by name. Only a person gives the final approval.
- **Three failures are errors.** A step cannot be closed as done while one stands: an image with no alt text, a third-party image with no credit, and a Markdown copy that differs from the Story's source. Closing a step despite one (as "done, accepted risk" with a reason) is a later piece of work; for now the checks report them clearly.
- **The checklist and the final review matter even more for sites that publish without a person's approval.**
- **No new gate.** Findings are advice. The checklist's own rule (an open step blocks publishing) is the gate.
- **Accuracy and natural writing beat every lens.** No keyword stuffing, no teaser that promises more than the Story delivers.

## The steps

The four lens steps are `review_people`, `review_reader_agents`, `review_search` and `review_social`. The per-Story checklist (`feat/story-checklist`) lists them and records who finished each. This definition names them and supplies their text; it does not edit `newsroom_process.py`.

## How agents read it

- Every agent profile (reporter, copywriter, editor) has the core context-pack layer `audience_lenses`, "How this Story will be reviewed for four audiences" ([context packs](newsroom-context-packs.md)). It is core, so it is never shed, and it is cut to the role: the copywriter reads the checks it can satisfy while writing, the editor the structure checks, and the reporter only what depends on research (source fidelity, attribution, where a picture came from).
- `papyrus stories next --story LINEAGE` prints one `lens` line for each lens step that is not done:

```
lens	review_people	not checked yet	no automatic checks yet; audience: people reading or skimming the page
```

  With `--json` the same lines are in `lenses`. A lens whose step the checklist records as done is left out. Until the checklist branch merges, every lens step reads as not checked yet (`lens_step_states` in `audience_lenses.py` is the one function to point at its records).

## The checks

Method: **checked by code** (deterministic), **judged by Jev** (a yes/no or pick-one question to the decision model), **drafted by Luna** (writing tasks only) or **a person decides**. Severity is the default: info is advice, warn must be mentioned in the step's note, error stops the step closing as done. "Runs in lens-check" says whether `papyrus stories lens-check` runs it yet. Model-judged checks are a later piece of work.

Where a check would want a length or a count, it compares to this site's own Stories and never to a number Papyrus invented. No check claims how a particular crawler, agent or platform behaves.

<!-- lenses:begin (generated from src/papyrus_content/audience_lenses.py; do not edit by hand) -->

### Reviewed for readers (`review_people`)

Audience: people reading or skimming the page.

**What good looks like.** A person who lands on the page, or skims it, gets an accurate headline, a dek that adds something, an opening that earns the next paragraph, headings that say something, pictures that are credited and described, and prose that does not read as machine filler. The Story is true: every claim a model wrote has been through the fact check.

| Check | What it asks | Method | Severity | Evidence | Runs in lens-check |
| --- | --- | --- | --- | --- | --- |
| P1 | The headline is present, is not a placeholder and is not another Story's headline | checked by code | warn | the title, and the other Story if duplicated | not yet |
| P2 | The Story has a dek (the summary line under the headline) | checked by code | warn | which field was used, or that the page will use the first paragraph | not yet |
| P3 | The dek adds something the headline does not | judged by Jev | info | the question, the answer and its probability | not yet |
| P4 | The headline does not promise what the Story does not deliver | judged by Jev | warn | the question, the answer and the sentence compared | not yet |
| P5 | The opening paragraph works as an opening | judged by Jev | info | the question and the answer | not yet |
| P6 | The headings are informative and in order | checked by code | info | the heading outline as read | not yet |
| P7 | Every image has alt text; an empty alt counts only as a deliberate decoration | checked by code | error | each image with its alt text present, empty or missing | not yet |
| P8 | Alt text is not a filename, the word "image" or a copy of the caption | checked by code | warn | the alt texts at fault | not yet |
| P9 | Alt text describes what the image shows | drafted by Luna | warn | the drafted text, the accepted text and who accepted it | not yet |
| P10 | Every third-party image is credited | checked by code | error | each image, where it came from and the credit found or missing | not yet |
| P11 | The prose is not machine filler or keyword stuffing | checked by code | warn | the editorial check run and its top findings | not yet |
| P12 | Charts and diagrams carry their meaning by marks and labels, not by colour alone | a person decides | info | one question per figure and whether a person looked | not yet |
| P13 | Every claim a model wrote has been fact-checked | checked by code | warn | claims held, by group, or that the draft check has not run | not yet |
| P14 | The Story is fair, engaging and worth reading | a person decides | n/a | the person's findings note | not yet |
| P15 | The readability is typical for this site | checked by code | info | the Story's value against the site's own median and spread | not yet |

### Reviewed for AI reader agents (`review_reader_agents`)

Audience: AI agents that read the page for a person.

**What good looks like.** An agent that is allowed to read the page for a person gets the Story as the author wrote it (verbatim Markus, not flattened Markdown), knows who wrote it and when, can tell each claim from the source it cites, and loses nothing if it reads only the Markdown copy. Where an agent cannot reach the page, the review says so and does not assume.

| Check | What it asks | Method | Severity | Evidence | Runs in lens-check |
| --- | --- | --- | --- | --- | --- |
| A1 | A Markdown copy will exist for this Story | checked by code | warn | the site setting, the Story's flags and the expected path | not yet |
| A2 | The Markdown copy is the Story's Markus source, every directive intact | checked by code | error | both versions' hashes and the first line that differs | not yet |
| A3 | Nothing the Markdown copy leaves out changes what an agent learns | checked by code | warn | each left-out block, its line and that it has no text equivalent | not yet |
| A4 | The Markdown copy carries the title, summary, byline, dates and canonical address | checked by code | warn | the header lines produced | not yet |
| A5 | Each outside claim cites a Reference and every citation resolves | checked by code | warn | cited keys, unresolved keys and uncited paragraphs with names, numbers or quotations | not yet |
| A6 | Claims can be told apart from their sources: attribution is explicit | judged by Jev | warn | the question, the answer and the paragraph | not yet |
| A7 | The first two paragraphs alone do not misstate the Story's conclusion | judged by Jev | warn | the question and the answer | not yet |
| A8 | Link text makes sense out of context | checked by code | info | the weak link texts | not yet |
| A9 | The headings form an outline an agent can navigate | checked by code | info | the outline | not yet |
| A10 | Images have a text equivalent in the Markdown copy | checked by code | warn | the images without one | not yet |
| A11 | Tables are tables, not pictures of tables | checked by code | info | images that look like tables (a guess) | not yet |
| A12 | After publishing: the Markdown copy is served and the page links to it | checked by code | warn | the addresses fetched, their status and content type | not yet |
| A13 | The site is live and open to readers | checked by code | info | whether the site asks readers to stay away | not yet |
| A14 | The Story does not claim access to a source it did not read | a person decides | n/a | the person's findings note | not yet |

### Reviewed for search (`review_search`)

Audience: search crawlers.

**What good looks like.** The page can be found and describes itself truthfully: a descriptive, unique title, a description written for people that fits the opening, the right canonical address, indexable when meant to be and not otherwise, structured data that is valid and matches the visible page, links from the rest of the site, and the topic's real terms because the Story is about them. Copy is never made worse to satisfy this lens.

| Check | What it asks | Method | Severity | Evidence | Runs in lens-check |
| --- | --- | --- | --- | --- | --- |
| S1 | The title is present, descriptive and unique among the site's Stories | checked by code | warn | the title, any duplicates and whether it is an outlier here | not yet |
| S2 | The description is the Story's own, not the site-wide fallback | checked by code | warn | which source the description came from | not yet |
| S3 | The description and title match the Story | judged by Jev | warn | the stored answer | not yet |
| S4 | Indexing is as intended | checked by code | warn | the flags and where they came from | not yet |
| S5 | The canonical address is correct | checked by code | warn | the resolved canonical address | not yet |
| S6 | Structured data is complete and matches the page | checked by code | warn | the structured data produced and the missing fields | not yet |
| S7 | The Story will be in the sitemap with a last-changed date | checked by code | warn | the rule that applied | not yet |
| S8 | The Story is linked from the rest of the site | checked by code | info | links in and out | not yet |
| S9 | The Story addresses the search targets it is meant for | judged by Jev | info | the targets checked and the answers | not yet |
| S10 | Target terms are used naturally, not stuffed | judged by Jev | warn | counts against the site's history and the flagged passages | not yet |
| S11 | The Story uses the name a reader would search for | judged by Jev | info | the answers | not yet |
| S12 | After publishing: the live page matches what was predicted | checked by code | warn | the fetch results | not yet |
| S13 | Search engines have indexed the page | checked by code | info | no evidence exists in Papyrus either way | not yet |
| S14 | The copy reads as written for people first | a person decides | n/a | the person's findings note | not yet |

### Reviewed for social previews (`review_social`)

Audience: people who see a link card before they click.

**What good looks like.** The three things a person sees in a share card (title, description, picture) are accurate, readable on their own, informative if the person never clicks, and consistent with the Story. The picture is real, credited if it is not ours, and described. If the Story has no picture of its own, the site's generic picture is used knowingly.

| Check | What it asks | Method | Severity | Evidence | Runs in lens-check |
| --- | --- | --- | --- | --- | --- |
| C1 | The preview resolves: the page and picture addresses can be built | checked by code | warn | the resolved addresses | not yet |
| C2 | The description is the Story's own, not the site fallback | checked by code | warn | which source the description came from | not yet |
| C3 | The Story has its own picture, or is knowingly using the site's | checked by code | info | where the picture came from | not yet |
| C4 | The picture file exists and its size and shape are known | checked by code | warn | the path, size and ratio | not yet |
| C5 | The picture has a description for the share card | checked by code | warn | the description used, or that none is emitted | not yet |
| C6 | A third-party picture is credited | checked by code | error | as P10 | not yet |
| C7 | Every name, number and quotation in the title and description is in the Story | checked by code | warn | the terms not found | not yet |
| C8 | The preview does not mislead | judged by Jev | warn | the answer and its probability | not yet |
| C9 | The preview stands alone as information | judged by Jev | info | the answer | not yet |
| C10 | The preview is not a teaser that withholds the point | judged by Jev | info | the choice and its probability | not yet |
| C11 | A drawn approximation of the card is shown to the approver | checked by code | info | the approximation and its inputs | not yet |
| C12 | After publishing: the live tags equal the predicted ones | checked by code | warn | the fetch results | not yet |
| C13 | The picture is tasteful, on brand and relevant | a person decides | n/a | the person's findings note | not yet |

<!-- lenses:end -->
