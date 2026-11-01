# Link exploration

One module, `papyrus_content.link_exploration`, turns any address (plus whatever is known about the item) into the canonical destination
and its readable text, or into a typed failure. Email intake, monitor stories and reference intake all call it.

```python
from papyrus_content.link_exploration import Context, explore

result = explore(url, Context(title=headline, summary=summary, anchor_text=link_text, sender=sender, publication=name),
                 want_text=True, accept=optional_check)
result.ok, result.url, result.text, result.via, result.failure
```

## What it does

1. **Resolve.** Follows HTTP redirects (300, 301, 302, 303, 307, 308), `<meta http-equiv="refresh">`, simple script redirects
   (`location = "..."`, `location.replace("...")`, only on a page with no article text) and the destination a known wrapper carries
   in its own address (Google `url?q=`, Substack redirect tokens, `?url=` redirectors on tracker-looking hosts). Wrappers that hide
   the destination (SendGrid `ls/click?upn=`, Beehiiv, Mailchimp) are simply followed. Tracking parameters (`utm_*`, `mc_*`, `fbclid`,
   `gclid`, `_bhlid`, ...) and the fragment are stripped from the canonical result.
2. **Read.** HTML and PDF text with the readers the monitor stories use (`ideas/excerpt.py`, `ideas/source_text.py`, `pdf_text.py`),
   including a thin page that wraps a PDF.
3. **Search.** If the address cannot be followed or read (and text was wanted), or cannot be followed at all (and only the address was
   wanted), the headline (else the summary, else the link text) is searched. The result whose title and snippet best cover the query
   words, with a small bonus for the publication's or sender's name in the domain, wins if its score reaches `MATCH_THRESHOLD` (0.6).
   It is returned with `via == "search"`, the query, the match score and the provider, and its `direct_failure` says why the original
   address fell short. The threshold is the one tunable; the score is always recorded so editors can judge.
4. **Fail with a reason.** `result.failure` (final) and `direct_failure` / `search_failure` are one of `REASONS`:
   `invalid_url`, `not_public`, `dns`, `timeout`, `connection`, `tls`, `loop`, `http_4xx`, `http_5xx`, `blocked`, `too_large`,
   `unreadable`, `unsafe_destination`, `no_query`, `search_unavailable`, `search_error`, `no_match`. A reason never contains an address.

## Thin landing pages: follow the page's own full-text link

Capture (`reference_capture.capture_source`, used by the monitoring router's enrichment and by reference curation) reads the fetched
HTML first. A journal or article-view page often fronts a PDF and carries only a meta description, so the page is **thin** when its
main-content text is no longer than its own meta description (no word or character cap). A thin page follows its own full-text link,
found in this order, and takes the text of the first one that is a readable PDF with more words than the page:

1. `<meta name="citation_pdf_url">` (also followed on a page that is not thin: it is the page's own declaration of its full text);
2. `<link rel="alternate" type="application/pdf">`;
3. anchors on the page's own site to a `.pdf`, then anchors on its own site labelled "PDF" or "full text".

No publisher is named. The PDF goes through the existing PDF path (`pdf_text`, page by page); GROBID still runs afterward on the
PDF bytes only where `BIBLICUS_GROBID_URL` is configured and the source looks like a paper. If no link yields a readable PDF, the
page's own text stays. The capture records where the text came from: `via` (`citation_pdf_url`, `alternate_pdf`, `linked_pdf`,
`full_text_link`) and `fullTextUrl` (the PDF's address; absent when the text is the page's own) on the router's enrichment row and
on the curation card's `capture`.

## Short-body statistic

`shortBodies` counts captured bodies shorter than 500 characters (`SHORT_BODY_CHARACTERS`): in the monitoring router's counts (per
item enriched in the run) and in the curation backfill counts. It is a report, never a gate: nothing is refused or retried because
of it, and a failed capture (no body) is counted under its own failure instead.

## Safety and limits

- Public http and https only. A private, loopback, link-local, credentialed or single-label address is refused (`not_public`) before any
  request; the default transport resolves the host, requires every resolved address to be global, and connects to the address it
  verified (no second lookup). The check runs again at every hop.
- Bounded only by real constraints: a redirect loop (`loop`), the response-size guard (HTML `MAXIMUM_BYTES`, PDF `MAXIMUM_PDF_BYTES`),
  a per-request timeout and one overall deadline (`DEADLINE_SECONDS`). There is no hop cap.
- The returned record holds the canonical destination only. The address that was passed in, and every hop, appear nowhere in the
  result, a reason or a log. `accept` lets a caller refuse a destination; email uses `safe_editorial_url`, so an account action or a
  secret-looking address is never offered (`unsafe_destination`, then the search fallback).
- Subscriber-specific links are fetched. That is the cost of research, and the newsletter sender may count it as a click.

## Search provider

`papyrus_content.link_search` defines `SearchProvider` (`search(query, limit) -> list[SearchHit]`). Its default is the configured provider
chain of `papyrus_content.web_search` (`WEB_SEARCH_PROVIDERS`, for example `openai,tavily`; `gemini,openai` when nothing is set), and
`TavilySearch` remains as Tavily on its own. Tavily's key is `TAVILY_API_KEY`; where an environment variable cannot hold a key (the
deployed Lambdas), `PAPYRUS_TAVILY_KEY_PARAMETER` (and `PAPYRUS_<PROVIDER>_KEY_PARAMETER` for the other providers, standard names
`/papyrus/search/<provider>-api-key`) names an SSM SecureString (for example `/papyrus/shared/tavily-api-key`) that is read once with
decryption; the function's role needs `ssm:GetParameter` on that parameter. A provider with no key is skipped; with no usable provider,
search is skipped and the reason is `search_unavailable`; a chain whose providers all failed is `search_error`.

## Where it is used

| Caller | How | What it keeps |
| --- | --- | --- |
| Email intake (`email_submission_intake._drain_manifest`) | Each unresolved wrapper in the manifest is explored (address wanted, `safe_editorial_url` as the acceptance check). Turned on by `handler()`; `EMAIL_LINK_EXPLORATION=off` turns it off. | The discovery carries the canonical destination; a found-via-search link carries `emailProvenance.linkExploration` (query, score, provider). A failure adds its reason to the receipt's `unresolvedReasons` counts and the link stays unrouted. |
| Editor "Resolve" action (`monitoring_view.monitoring_email_resolve_article_link`) | Explores the selected candidate with its title as context. | The response and the recorded `EMAILRESOLVED` row hold the destination (and `foundViaSearch` when searched). The UI says so and asks the editor to check. |
| Monitor stories (`ideas/monitor_stories.explore_item`) | Source text for the model: direct read, else search. | A story drafted from a searched page has `sourceText: "page found by search"` and `sourceExploration`. A skipped item records `readFailure`, `directFailure`, `searchFailure`. |

## Deployed configuration

| Setting | Where | Meaning |
| --- | --- | --- |
| `TAVILY_API_KEY` | environment | The Tavily key. Used first. |
| `PAPYRUS_TAVILY_KEY_PARAMETER` | environment | SSM SecureString holding the key, for Lambdas and tasks. |
| `TavilyKeyParameter` (stack parameter) | `papyrus-monitoring` (router and collector) and `papyrus-email-submissions` stacks | Default `/papyrus/shared/tavily-api-key`; sets `PAPYRUS_TAVILY_KEY_PARAMETER` on the router and the email receiver and attaches a policy granting `ssm:GetParameter` on that parameter and `kms:Decrypt` via SSM. Empty disables search. |
| `EMAIL_LINK_EXPLORATION` | email intake Lambda environment | `off` disables exploring wrappers at intake (default on). |

The lambdas that explore (email intake, monitoring view, the knowledge-run task) also need outbound internet access.
