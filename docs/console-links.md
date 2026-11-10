# Console links: hand the editor the item you worked on

When an agent works on a Story, Reference, Concept or Assignment for an editor, the last thing it says is a link that opens
exactly that item in the newsroom console. Never describe where to click; print the link.

```bash
papyrus links --story LINEAGE|SLUG [--version N|VERSION_ID] [--reference REFERENCE_ID|LINEAGE] [--concept NAME|NODEKEY] \
              [--assignment ID] [--review ID] [--console-url URL] [--json]
```

`links` is read only. It checks each id against the site first (an id that does not exist is an error, never a dead link) and prints
`links<TAB>kind<TAB>url<TAB>note` rows, or JSON with `--json`. These commands also print a `console` row for the item they just wrote
or read, so you rarely need `links` by itself:

| Command | Row it adds |
| --- | --- |
| `stories create` | `stories create console story <url>` (the first version), and the drawer and checklist rows |
| `stories save-version` | the editor page of the version just saved |
| `stories show` | the editor page of the current version |
| `references show` | `console: <url>` of the Reference |

Say the links in your final report. A Story you edited gets its `story` link (the exact version you saved); a Story you only
reported on gets its `story-board` link (always the latest version, with the checklist).

## Where the console is

The CLI never guesses the console address. It takes the first of: `--console-url`, `PAPYRUS_CONSOLE_URL`, then `console_url` from the
signed-in site's public site file (`/.well-known/papyrus-site.json`, written by `lib/cli-site-document.ts` from `PAPYRUS_CONSOLE_ORIGIN`,
else `PAPYRUS_SITE_ORIGIN`, plus the brand's `newsroomBasePath`). A site that does not publish it yet (it runs an older release) fails with
a message that says so. Until then pass `--console-url https://newsroom.<site>/newsroom`. Console-only hosts (anth.us, Pilobolus) serve the
console at the root of their host, so their address has no `/newsroom`: use the published one, not a typed one. One definition builds every
address: `src/papyrus_content/console_links.py`.

## The routes

`BASE` is the console address above (for example `https://newsroom.machines-on-machines.anth.us/newsroom`).

| Item | Address | Needs | Wrong id | Not signed in |
| --- | --- | --- | --- | --- |
| Story, one exact version (draft or published) | `BASE/articles/<version id>` | the version record id (`stories versions` prints it) | "That article was not found." banner. A lineage id here is a wrong id. | Editor sign-in gate; sign-in returns to this page |
| Story, by lineage id (drawer) | `BASE/articles?open=contentItem%3A<lineage id>` | query `open` | The board opens with no drawer, silently. Also silent when the Story's column is not loaded (published and spiked columns load when opened) | Editor sign-in gate; the query survives sign-in |
| Story checklist | same as the drawer | | | The checklist is a panel inside the drawer; it has no address, hash or anchor of its own |
| Reference | `BASE/references/<lineage id>` | the lineage id (`reference-...`), not the `-v1` record id | "Reference not found: <id>" | Editor sign-in gate |
| Concept | `BASE/concepts?node=<lineage id>` | query `node` (a concept's lineage id, `semantic-node-...`) | "That concept page was not found." | Editor sign-in gate |
| Assignment | `BASE/assignments/<assignment id>` | the Assignment id | The assignments page opens with nothing selected, silently | Editor sign-in gate |
| Review item (Notification Center) | `BASE/needs-me/<item id>` | a review request id (`rr-...`), or a Reference lineage id waiting for a decision | "The item in this link is not waiting for you any more" | Editor sign-in gate |

Notes the table cannot hold:

- **Unpublished drafts work.** The version page reads the Item record by id whatever its status, so a link to a draft shows that draft's
  text (not the published one). A version link goes stale only in the sense that it keeps showing that version after a newer one is saved;
  use the drawer link to follow the latest.
- **The drawer link assumes the Story board is at `/articles`.** A site that renames its content item (the board path is the plural of the
  content item name) redirects `/articles` to its own board and the redirect drops the query, so the drawer opens as a plain board. The
  version page is not affected.
- **Concept: use `?node=`.** `BASE/concepts/<id>` is what the page writes to the address bar while you click around, but a fresh load of it
  shows the concept index (the server reads that segment as a topic category). Only `?node=` opens the concept page on a first load.
- **A console-only host** (`newsroomBasePath` of `""`) has no `/newsroom` in any address, and `/newsroom/...` on it redirects to the public site.
- **No sign-in is passed in a link.** An editor who is not signed in sees the sign-in control on the same page and returns to it afterwards.

## Not built yet

- A route for a Story's checklist of its own (a hash or `?panel=checklist` that opens the drawer scrolled to it).
- A route for one Concept that survives a fresh load at `/concepts/<id>`.
- A drawer link that works for a Story whose column is not loaded, and for a board with a renamed content item.
- An MCP `links` tool: the MCP layer does not share the CLI's command definitions, so adding one would be a second copy.

Kanbus tasks track these.
