---
name: page-refresh
description: Use when an edit must be visible on a Papyrus site now instead of after the cache lifetime: refresh a page, a Story's pages, or the index pages, or re-render pages from the deployed hooks.
---

# Page refresh

Papyrus sites keep a page at the edge for the cache lifetime (an hour by default). That stays. This skill is for the moments an edit has to be seen now, through the `papyrus ops content refresh` and `rerender` commands or the `site_*` MCP tools. They are the same operations, with the same input and the same JSON result (`docs/site-hosting.md`, "Refreshing pages on demand").

The one command for the editing loop is `papyrus ops content update-live --story LINEAGE` (`site_update_live`): it re-projects the Story, purges exactly its pages and the index pages that list it (both URL forms), and checks the live page shows the new version. Start with it. The first call is a dry run that lists the paths; read the list, then repeat it with `--run`.

For anything else, pick the smallest operation that covers the edit, and look before you purge:

| Need | MCP tool | Command |
| --- | --- | --- |
| One or a few pages look old | `site_refresh_pages` (`paths`) | `refresh --path /articles/my-story/` |
| A Story was edited: its page, and the home page, list and section pages that show it | `site_refresh_story` (`storyLineageId`) | `refresh --story LINEAGE` |
| The index pages look old (a ranking or a card changed) | `site_refresh_indexes` | `refresh --indexes` |
| A template or hook change is deployed but existing pages still have the old markup | `site_rerender_pages` (`scope`: `story`, `indexes` or `all`) | `rerender --story LINEAGE`, `--indexes` or `--all` |

Rules:

- NEVER run `aws cloudfront create-invalidation` yourself, in any form. It bypasses the cap and the dry-run rule, and once purged 625 paths (about 3 USD) for one stale article. All invalidation goes through these tools.
- The cap is 25 paths per call. A refusal names `--force-paths N`; that flag is for a person who has read the list, never something to add on your own because a call was refused. `--indexes`, `--all` and a re-render never imply it.
- Run with `dryRun: true` (`--dry-run`) first when you are unsure: it prints the exact paths and the most they can cost, and changes nothing.
- A page is purged under every URL form it is cached under (`/dir/`, `/dir/index.html`) and as its Markdown twin. Do not purge one form by hand and call it done.
- Never ask for a wildcard or the whole site. A path with `*` is refused. `rerender --all` rewrites every page and purges them all by name: dry-run it and say how many paths it is before running it.
- A publish already purges the pages it rewrote on a site that invalidates on Save. Use a refresh for what a publish did not reach: index pages that were not rewritten, a story edited some other way, a site that does not invalidate on Save.
- Read the answer: `rendered.ok` (re-render only) and `invalidation.ok` are separate. `invalidation.status` is `invalidated` with the CloudFront invalidation `id` and `status` (`InProgress` completes in seconds to a minute), or `failed` with the reason. The first 1,000 paths a month are free, then 0.005 USD each.
- From the signed-in lane a re-render of the index pages or the whole site is scheduled, not finished, when the answer says `scheduled`.
