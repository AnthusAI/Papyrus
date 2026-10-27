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

`papyrus_content.link_search` defines `SearchProvider` (`search(query, limit) -> list[SearchHit]`) and one implementation, `TavilySearch`,
which uses the same endpoint and `TAVILY_API_KEY` as the newsroom's web search. Where an environment variable cannot hold the key (the
deployed Lambdas), `PAPYRUS_TAVILY_KEY_PARAMETER` names an SSM SecureString (for example `/papyrus/shared/tavily-api-key`) that is read
once with decryption; the function's role needs `ssm:GetParameter` on that parameter. With neither, search is skipped and the reason is
`search_unavailable`.

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
| `EMAIL_LINK_EXPLORATION` | email intake Lambda environment | `off` disables exploring wrappers at intake (default on). |

The lambdas that explore (email intake, monitoring view, the knowledge-run task) also need outbound internet access.
