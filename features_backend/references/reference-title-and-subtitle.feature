Feature: A Reference keeps its source's own title and subtitle, and a model writes only what is missing
  Every Reference card shows a title and a line under it. When the source supplied both, Papyrus shows them
  word for word and asks no model. When the line under the title is missing, a model is asked to write one,
  with a web search only where the publication allows it, and the card records that the line was generated.
  A generated line that says nothing (a single generic word, a web address) is thrown away rather than shown,
  and a model that fails never costs the Reference the title it already had.

  Scenario: The source's own title and subtitle are kept word for word and no model is asked
    Given a Reference whose source supplied the title "Teens and AI Companions" and the subtitle "A national survey of 1,060 teenagers"
    When Papyrus settles the Reference's title and subtitle
    Then the Reference is titled "Teens and AI Companions" with the subtitle "A national survey of 1,060 teenagers"
    And both are recorded as the source's own words
    And no model was asked

  Scenario Outline: A missing subtitle is written by a model, which searches the web only where that is allowed
    Given a Reference titled "Teens and AI Companions" with no subtitle
    And web search is <web search> for the publication
    And the model would write the subtitle "Survey finds routine AI companion use among U.S. teens"
    When Papyrus settles the Reference's title and subtitle
    Then the Reference is titled "Teens and AI Companions" with the subtitle "Survey finds routine AI companion use among U.S. teens"
    And the subtitle is recorded as generated
    And the model that was asked is the one that <searches or not>

    Examples:
      | web search | searches or not      |
      | off        | cannot search the web |
      | on         | searches the web      |

  Scenario Outline: A generated subtitle that says nothing is not shown
    Given a Reference titled "Teens and AI Companions" with no subtitle
    And web search is off for the publication
    And the model would write the subtitle "<empty words>"
    When Papyrus settles the Reference's title and subtitle
    Then the Reference is titled "Teens and AI Companions" with no subtitle
    And a warning says the generated subtitle was rejected because it <reason>

    Examples:
      | empty words                                                  | reason                      |
      | Study                                                        | is a generic one-word label |
      | https://phys.org/news/2025-07-quarters-teens-ai-companions.html | looks like URL              |

  Scenario: A model that fails costs the Reference nothing it already had
    Given a Reference titled "Teens and AI Companions" with no subtitle
    And web search is off for the publication
    And the model asked for a subtitle fails with "rate limited"
    When Papyrus settles the Reference's title and subtitle
    Then the Reference is titled "Teens and AI Companions" with no subtitle
    And a warning names the failure "rate limited"

  Scenario: A Reference whose identifier could not be checked is held back, and no model is asked
    Given a Reference titled "Teens and AI Companions" with no subtitle
    And the check of the Reference's identifier failed with "DOI lookup timed out"
    When Papyrus settles the Reference's title and subtitle
    Then settling is blocked with the reason "DOI lookup timed out"
    And no model was asked
