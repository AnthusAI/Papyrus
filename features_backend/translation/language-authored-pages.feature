Feature: An authored page can be rendered in each language that has its file
  An authored page (`pages` in projection.json) is the primary language's only, unless it opts in with `"languages": "localize"`. An opted-in page is rendered under the
  prefix of each public language that has the page's file in that language (`pages/findings.md` is `pages/findings.es-419.md` in Spanish), with its title and description from the
  language's interface strings (`page.<id>.title`, `page.<id>.description`). A language without the file, or without the page's title string, does not render the page, and the page is no alternate in that language:
  no English text is ever put in a Spanish page for lack of a translation. The page and its localizations name each other (`hreflang`, the switcher's alternates, the link map).

  Background:
    Given a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root
    And Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings
    And an authored page "findings" at "findings" titled "Findings" that opts in to languages, with a Spanish file titled "Hallazgos" and no Chinese file
    And the English article "the-sound" titled "The sound that can give away where you live" is published

  Scenario: A language with the page's file renders it under its prefix with its own title
    When the multilingual site is projected
    Then the written page "es/findings/index.html" exists and its title is "Hallazgos"
    And the written page "findings/index.html" is the English page titled "Findings"

  Scenario: A language without the file does not render the page
    When the multilingual site is projected
    Then the written page "zh/findings/index.html" does not exist

  Scenario: The page and its Spanish localization are each other's alternates, and Chinese is not one
    When the multilingual site is projected
    Then the written page "findings/index.html" lists hreflang "en" and "es" and not "zh-Hans"
    And the written page "es/findings/index.html" lists hreflang "en" and "es" and not "zh-Hans"

  Scenario: A page that does not opt in is not rendered in any language
    Given an authored page "about" at "about" titled "About" that does not opt in, with a Spanish file titled "Acerca de"
    When the multilingual site is projected
    Then the written page "es/about/index.html" does not exist

  Scenario: A language that has the file but no title string for the page does not render it
    Given the site is built again with no Spanish title string for the page "findings"
    When the multilingual site is projected
    Then the written page "es/findings/index.html" does not exist
    And the written page "findings/index.html" lists hreflang "en" and not "es"

  Scenario: A page can take its title from another string, as a section page takes its section's label
    Given an authored page "section-security" at "security" titled "Privacy & Security" that takes its Spanish title from the string "section.security.label" which is "Privacidad y seguridad"
    When the multilingual site is projected
    Then the written page "es/security/index.html" exists and its title is "Privacidad y seguridad"
