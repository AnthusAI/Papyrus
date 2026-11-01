Feature: Web search runs on whichever provider configuration names, and falls back when one cannot answer
  Papyrus searches the web in several places: link exploration, reference research and the web-search monitors. They all go
  through one provider layer that speaks to Tavily, OpenAI, Perplexity, Gemini and Amazon Bedrock and gives every caller the same
  hits: a URL, a title, a snippet and, where the provider has one, a score. Which provider answers is configuration, never code:
  WEB_SEARCH_PROVIDERS is an ordered list, a fallback chain, and a monitor may carry a chain of its own. When a provider cannot
  answer because its plan is used up, its key is refused or it is rate limited, the next one answers, and the result says who
  answered and why the others were passed over, in words an operator can read in the monitor log. A provider whose key was never
  configured is simply not available; that is not a failure. When nothing is configured the chain runs from cheapest to dearest:
  Tavily, then Perplexity, then OpenAI. Gemini is used only where an operator names it.

  Scenario: The configured provider answers
    Given web search is configured with the providers "perplexity"
    And Perplexity answers with one page
    When a search for "licensing news" runs
    Then Perplexity answered
    And the hit has the page's URL, title and snippet
    And no provider was skipped

  Scenario: The old single-provider setting still works
    Given web search is configured with the old single setting "openai"
    Then the provider chain is "openai"

  Scenario: With nothing configured the cheapest provider answers first
    Tavily is free while it has credits, Perplexity costs about $5 per 1,000 searches and OpenAI about $10 plus tokens, so the chain
    runs from cheapest to dearest. Gemini's grounded search, about $14 per 1,000, is used only where an operator names it.
    Given web search has no provider configuration at all
    Then the provider chain is "tavily,perplexity,openai"

  Scenario: Tavily's exhausted plan falls through to the next provider
    Given web search is configured with the providers "tavily,openai"
    And Tavily refuses with its plan-exhausted status 432
    And OpenAI answers with one source
    When a search for "licensing news" runs
    Then OpenAI answered
    And the result says "tavily: plan exhausted (432)"

  Scenario: A provider with no key is skipped as unavailable, not counted as a failure
    Given web search is configured with the providers "gemini,tavily"
    And no Gemini key is configured
    And Tavily answers with one page
    When a search for "licensing news" runs
    Then Tavily answered
    And Gemini was skipped as unavailable and not as a failure

  Scenario: A key held in a Parameter Store parameter is read by name
    Given web search is configured with the providers "perplexity"
    And the Perplexity key is only in the parameter "/papyrus/search/perplexity-api-key"
    And Perplexity answers with one page
    When a search for "licensing news" runs
    Then Perplexity answered
    And the parameter "/papyrus/search/perplexity-api-key" was read

  Scenario: When every provider fails the error names each failure
    Given web search is configured with the providers "tavily,openai"
    And Tavily refuses with its plan-exhausted status 432
    And OpenAI refuses the key with status 401
    When a search for "licensing news" runs
    Then the search fails with "tavily: plan exhausted (432); openai: authentication failed (401)"

  Scenario: A monitor can override the chain in its own configuration
    Given web search is configured with the providers "tavily"
    And a web monitor whose configuration says searchProviders is "perplexity"
    And Perplexity answers with one page
    When the monitor searches through its provider chain
    Then Perplexity answered the monitor's searches
    And Tavily was never asked

  Scenario: A monitor falls back when Tavily's plan is used up and records why
    Given a web monitor whose configuration says searchProviders is "tavily,perplexity"
    And Tavily refuses with its plan-exhausted status 432
    And Perplexity answers with one page
    When the monitor searches through its provider chain
    Then the monitor's run recorded the page as found
    And the query run says Perplexity answered and "tavily: plan exhausted (432)"
