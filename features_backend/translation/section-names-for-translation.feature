Feature: A section is named for translation from its title and the site's own sections file
  A publication that writes in more than one language shows each section's name in the reader's language.
  Before a name can be translated, the newsroom has to say what the section is called in the language the
  publication is written in, and give the translator enough to choose the right word: a short description and
  one line about what the section covers.

  The name a reader already sees on the home page wins. A site keeps those names and descriptions in its
  sections file, so when the file names a section, that label and description are what get translated. A section
  the file does not mention is named by its title in the newsroom. The newsroom reads each section it was asked
  about once, by its id, and never lists every section to find them.

  Background:
    Given a publication written in "en" with these sections in the newsroom:
      | id       | title            | editorial mission                                   |
      | news     | Weekly news        | What happened this week in the field, with sources. |
      | analysis | Analysis         | Longer pieces that explain why something matters.   |
      | tools    | Tools and method |                                                     |

  Scenario: A section the sections file names is called what readers already see
    Given the site's sections file says:
      | id   | label | description                    |
      | news | News  | The week's reporting, sourced. |
    When the newsroom names the section "news" for translation
    Then the section "news" is to be translated from the name "News"
    And its description for the translator is "The week's reporting, sourced."
    And the translator is told that it covers "What happened this week in the field, with sources."

  Scenario: A section the sections file does not mention is called by its newsroom title
    Given the site's sections file says:
      | id   | label | description                    |
      | news | News  | The week's reporting, sourced. |
    When the newsroom names the section "analysis" for translation
    Then the section "analysis" is to be translated from the name "Analysis"
    And it has no description for the translator

  Scenario: A site with no sections file names every section by its newsroom title
    Given the site has no sections file
    When the newsroom names the sections "news" and "tools" for translation
    Then the section "news" is to be translated from the name "Weekly news"
    And the section "tools" is to be translated from the name "Tools and method"

  Scenario: A sections file may be a plain list or hold its list under "sections"
    Given the site's sections file holds its list under "sections":
      | id       | label    | description         |
      | analysis | Explains | Why things matter.  |
    When the newsroom names the section "analysis" for translation
    Then the section "analysis" is to be translated from the name "Explains"
    And its description for the translator is "Why things matter."

  Scenario: Every name is in the language the publication is written in
    Given the site has no sections file
    When the newsroom names the sections "news" and "analysis" for translation
    Then every name to be translated is marked as written in "en"

  Scenario: A section that does not exist is refused by name
    Given the site has no sections file
    When the newsroom names the section "sports" for translation
    Then naming is refused, saying there is no section "sports"

  Scenario: Each section is read once by its id, and the sections are never listed
    Given the site has no sections file
    When the newsroom names the sections "news" and "tools" for translation
    Then the newsroom read the section "news" once and the section "tools" once
    And the newsroom never listed the sections
