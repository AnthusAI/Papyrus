Feature: A localized authored page lives at its translated segment
  The path of an authored page that a language renders is translated with the language's segment table (`languages.segments`), like a section's. The page is still the
  alternate of the English page, named by `hreflang` at its translated address; the English-segment address is only a redirect (the edge keeps it), never a second page.

  Background:
    Given a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root
    And Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings
    And the language segments are "es-419": findings is "hallazgos"
    And an authored page "findings" at "findings" titled "Findings" that opts in to languages, with a Spanish file titled "Hallazgos" and no Chinese file
    And the English article "the-sound" titled "The sound that can give away where you live" is published

  Scenario: The page is at the translated address and the English segment is not a page
    When the multilingual site is projected
    Then the written page "es/hallazgos/index.html" exists and its title is "Hallazgos"
    And the written page "es/findings/index.html" does not exist

  Scenario: The English page and the Spanish page name each other at their addresses
    When the multilingual site is projected
    Then the written page "findings/index.html" names "/es/hallazgos/" in hreflang
    And the written page "es/hallazgos/index.html" names "/findings/" in hreflang

  Scenario: The old English-segment address redirects to the translated page
    When the multilingual site is projected
    Then it sends "/es/findings/" to "/es/hallazgos/"
