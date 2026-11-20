Feature: A guideline scoped to a channel reaches the drafter for that channel, and a section adds to it and never loosens it
  Each network has its own craft: the hook, the length, links, tags, tone, image shape. A rule file may be scoped to a channel (channel/x, channel/linkedin, channel/email). When
  guidelines are resolved for writing on a channel, the rules scoped to that channel are laid in with the publication's and the section's, and the rules of every other channel are
  left out. The drafter for X reads channel/x and not channel/email. A channel rule is laid like any other rule file: it adds, and a section's rule with the name of an earlier
  rule's is left out with a warning, so what was written first stands and nothing is loosened. A field file stays in its own set's scope. This step touches no live account.

  Background:
    Given a site with no writing guidelines yet
    And the site's writing guidelines are saved from a folder with the rule "plain-claims" at severity error that avoids "we believe"
    And the site's writing guidelines also hold the rule "short-hook" scoped to the channel "x" at severity warn limited to 80 characters
    And the site's writing guidelines also hold the rule "subject-line" scoped to the channel "email" at severity warn limited to 60 characters

  Scenario: Writing for X reads the publication's rules and X's own, and not email's
    When the rule files and fields are resolved for the channel "x"
    Then the resolved rule files are "plain-claims" from the publication then "short-hook" from the publication

  Scenario: Writing for email reads email's rules and not X's
    When the rule files and fields are resolved for the channel "email"
    Then the resolved rule files are "plain-claims" from the publication then "subject-line" from the publication

  Scenario: Writing for no channel reads no channel's rules
    When the rule files and fields are resolved for no channel
    Then the resolved rule files are "plain-claims" from the publication

  Scenario: The answer says which channel it was resolved for
    When the rule files and fields are resolved for the channel "x"
    Then the resolved answer is for the channel "x"

  Scenario: A section adds a rule on a channel and never loosens the publication's
    Given the section "news" saves a folder with the channel rule "short-hook" for "x" at severity guidance limited to 200 characters
    When the rule files and fields are resolved on the channel "x" for the section "news"
    Then the resolved rule files are "plain-claims" from the publication then "short-hook" from the publication
    And the rule "short-hook" has the severity warn
    And the resolved answer gives the warning "rule_file_shadowed"

  Scenario: A section's own rule for a channel is added after the publication's
    Given the section "news" saves a folder with the channel rule "news-hook" for "x" at severity warn limited to 100 characters
    When the rule files and fields are resolved on the channel "x" for the section "news"
    Then the resolved rule files are "plain-claims" from the publication then "short-hook" from the publication then "news-hook" from the section

  Scenario: A field file cannot be scoped to a channel
    When an admin saves a set whose tone file is scoped to the channel "x"
    Then the guideline save is refused saying "must be publication"

  Scenario: The text the X drafter is given names X's rule and not email's
    When the rule files and fields are resolved for the channel "x"
    Then the writing text for the drafter names the rule "short-hook" and not the rule "subject-line"
