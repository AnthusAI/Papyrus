Feature: Multi-search asks several search providers about one assignment and merges what they find
  Most assignments are researched with the site's normal search, which is Perplexity. Multi-search is a special mode that an editor
  reserves for the assignments that deserve a wider net: it is chosen per assignment as the type research.multi, beside
  research.tavily-deep, and it is never the default and never runs on its own. When an editor runs it, one model call plans a
  handful of search queries from the assignment's brief, each with a short purpose. Every query then goes to every search provider
  that is configured, in parallel. The pages come back merged: a page that two providers both found is one source that names both
  of them, and a page only one provider found is kept, because a single provider finding something is still a lead. A second model
  call writes the research packet from the merged sources, with each claim citing the sources behind it, where the sources
  disagree, and the questions nobody answered. The packet is stored exactly like any other research packet, so the newsroom shows
  it as it always does, and it carries which providers found each source and what each provider contributed, so the site can see
  which providers earn their cost. One provider failing never stops the run while another answers. If none answers, no packet is
  made and the assignment records a clear error.

  Scenario: A page two providers both found is one source that names both
    Given the multi-search providers "gemini" and "openai" both find the page "https://example.org/glide"
    When the editor runs multi-search on the assignment
    Then the packet has one source for "https://example.org/glide"
    And that source names the providers "gemini, openai"
    And the proposed reference for that source names the providers "gemini, openai"

  Scenario: A page only one provider found is kept
    Given the multi-search provider "gemini" alone finds the page "https://only-gemini.example/a"
    And the multi-search provider "openai" finds other pages
    When the editor runs multi-search on the assignment
    Then the packet has a source for "https://only-gemini.example/a"
    And that source names the providers "gemini"

  Scenario: One provider failing does not stop the run, and the failure is recorded
    Given the multi-search provider "gemini" has used up its plan
    And the multi-search provider "openai" finds other pages
    When the editor runs multi-search on the assignment
    Then a research packet is made from the sources "openai" found
    And the packet records that "gemini" failed with "plan_exhausted"

  Scenario: When no provider answers there is an error message and no packet
    Given every multi-search provider refuses its key
    When the editor runs multi-search on the assignment
    Then no research packet is made
    And the assignment records the error "no search provider answered"

  Scenario: The packet shows what each provider contributed
    Given the multi-search providers "gemini" and "openai" both find the page "https://example.org/glide"
    And the multi-search provider "gemini" alone finds the page "https://only-gemini.example/a"
    When the editor runs multi-search on the assignment
    Then the packet's contribution for "gemini" shows 2 hits and 1 unique sources
    And the packet's contribution for "openai" shows 1 hits and 0 unique sources
    And every provider's contribution shows its queries run, its failures and its elapsed milliseconds

  Scenario: The packet cites its sources and says where they disagree
    Given the multi-search providers "gemini" and "openai" both find the page "https://example.org/glide"
    When the editor runs multi-search on the assignment
    Then each claim in the packet cites sources that exist
    And the packet names where the sources disagree and what stayed open

  Scenario: Multi-search is never the default
    When an editor creates a research assignment without choosing a type
    Then the assignment is a research.candidate and not a research.multi
