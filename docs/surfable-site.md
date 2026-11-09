# Surfable site: relations a page is built from

Epic PPY-6bd9810f. Goal (Ryan, 2026-11-09): keep readers on our site. A page of the standard front end now knows three things about a published Story that
live in `SemanticRelation` rows rather than in its front matter. `papyrus_content/projection/site_relations.py` reads them; the standard projector turns
them into data a page and a site hook can use.

| Fact | Relation | What the page gets |
| --- | --- | --- |
| A Story is based on a Reference | `uses_evidence` from the Story to the Reference, metadata `role: based_on` | A cited source whose address matches an accepted Reference's `sourceUri` links to our newest published Story based on it (`internalUrl`, see [markus content markup](markus-content-markup.md#how-the-bibliography-links-a-source)). |
| A Story is about a concept | `mentions` or `related_to` from the Story to a `SemanticNode` | `page.concept_links`: the concept pages that are published (`entityKey` is the part of `nodeKey` after `editor_concept--`), most used first, then by name. Rejected nodes are skipped. |
| A Story points a reader to a Reference ("read this source too") | `see_also` from the Story (an `item`) to a `Reference`, written by `papyrus stories link-story --story S --reference R` (kind `item.reference-link`, directional) | `page.related_references`: the **accepted** References (never pending, recommended or rejected), newest linked first, each `{referenceId, lineageId, title, url, host, image, summary, medium, acceptedAt, note}`; `image`, `summary` (the generated card summary), `medium` and `note` are `None` when there is none. The captured text is never included. Citing or consulting a Reference (`uses_evidence`) is the reporting trail and never appears here. Rejected or suggested links are ignored. |
| A Story is related to another Story | `see_also` between two `item` rows, symmetric | `page.related_stories`: the related published Stories, newest first, each `{itemId, type, section, title, url, image, summary, date}`. Never the Story itself, never an unpublished one. |

`page.concept_links`, `page.related_references` and `page.related_stories` are fields of `StandardPage` on item pages (empty on wiki pages). A hook takes `page` and draws them.

## Finding what to link

The links above are written by people or agents; the candidates come from the same relations. `papyrus stories suggest-links --story S` (read only, no model call)
starts from the Story's concept edges (`tagged_with`, `related_to`, accepted `mentions`), adds the concepts near them (confirmed `concept.link` rows, then co-occurrence
on published Stories and accepted References), scans the carriers of those concepts, and prints a ranked **See also** / **Posts** / **Related findings** list with the
shared concepts and the ready `link-story` command. It leaves out what the page already shows (`see_also` in either direction, `uses_evidence` and `see_also` References).
`papyrus knowledge concepts search "text"` finds a concept to tag with when the story has none. See [Suggesting related content](story-reporting.md#suggesting-related-content).

## What the read costs

It is bounded and indexed; nothing scans a table. For N published Stories: `ceil(N/25)` requests on `semanticRelationsBySubjectState` (the Stories'
own relations), the same number on `semanticRelationsByObjectState` (Stories that point at them), one `Reference` read per 25 `based_on` relations and one
`SemanticNode` read per 25 concepts that have a public page. Machines on Machines (about 120 published Stories) is roughly ten to fifteen requests per
site index. The result rides on `SiteIndex.relations`; the directory source (a local checkout) has none.

## How stale pages are rebuilt

`StandardMarkusProjector.shared_inputs` now includes `SiteRelations.digest_input()`. When a Story is published or withdrawn, a concept page appears, or a
relation changes, the digest changes, the engine sets `follow_up_item_pages`, and the item pages are rendered again; a page whose bytes did not change is
not written or purged. Cost: the follow-up renders every item page of the site in memory. A finer dependency (only the pages that cite a given address)
would need a per-page input digest that the engine does not have; none was invented.
