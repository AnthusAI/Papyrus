Feature: A section's guideline files are laid over the site's and never loosen them
  The rule files of a set are part of what the resolver lays over. The publication's rule files come first, then the section's, each marked with the layer it came
  from. A section adds rules; it never replaces or removes one. A section's rule with the name of the site's is left out with a warning, so the site's severity
  stands. A rule written for the publication cannot be saved into a section's set, and the other layering rules (prose added in order, words to avoid joined, locked
  choices, binding rules the publication's alone) are unchanged by guidelines being files. This step touches no live account.

  Background:
    Given a site with no writing guidelines yet
    And the site's writing guidelines are saved from a folder with the rule "plain-claims" at severity error that avoids "we believe"

  Scenario: The section's rule is added after the site's, each marked with its layer
    Given the section "news" saves a folder with the rule "short-leads" at severity warn limited to 120 characters
    When the rule files and fields are resolved for the section "news"
    Then the resolved rule files are "plain-claims" from the publication then "short-leads" from the section

  Scenario: A section cannot loosen the site's rule by giving its own the same name
    Given the section "news" saves a folder with the rule "plain-claims" at severity warn that avoids "arguably"
    When the rule files and fields are resolved for the section "news"
    Then the resolved rule files are "plain-claims" from the publication
    And the rule "plain-claims" has the severity error
    And the resolved answer gives the warning "rule_file_shadowed"

  Scenario: A section with no files of its own gets the site's rules
    When the rule files and fields are resolved for the section "sports"
    Then the resolved rule files are "plain-claims" from the publication

  Scenario: Prose and words to avoid still layer by their own rules beside the rule files
    Given the section "news" saves the structured fields tone "Brisk." and avoids "leverage"
    When the rule files and fields are resolved for the section "news"
    Then the words to avoid include "leverage"
    And the resolved rule files are "plain-claims" from the publication
