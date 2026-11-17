Feature: Each guideline file with severity error or warn derives one editorial check, and no other check is touched
  Saving writing guidelines keeps the editorial checks drawn from them in step, as before: the structured fields give the checks they always gave. In addition each rule
  file with the severity error or warn gives one check of its own, named after the file: a phrase detector for its words to avoid and a pattern detector for each
  pattern. A rule that needs judgement (prose only) gives a check with no detector, shown to the writer and the editor, that finds nothing by itself. A file with the
  severity guidance gives no check. The check records the guidelines it was drawn from as its source. A check that is hand-written, from a starter pack, or edited in
  the Editorial checks panel is never created over, updated or disabled by a save, and a rule file that is removed disables its check.

  Background:
    Given a site with no writing guidelines and with no editorial checks yet

  Scenario: An error rule and a warn rule each derive one check
    When an admin saves a folder with the rule "plain-claims" at severity error that avoids "we believe" and the rule "short-leads" at severity warn with a pattern
    Then the check "publication#guideline-plain-claims" exists with severity error and the phrase "we believe"
    And the check "publication#guideline-short-leads" exists with severity warn and a pattern detector
    And both checks name the writing guidelines of the site as their source

  Scenario: A guidance file and a prose-only rule
    When an admin saves a folder with the rule "tone-notes" at severity guidance that avoids "arguably" and the rule "say-it-plainly" at severity error with only prose
    Then there is no check "publication#guideline-tone-notes"
    And the check "publication#guideline-say-it-plainly" exists with no detector

  Scenario: A hand-written check is never touched
    Given a hand-written check "guideline-plain-claims" for the publication
    When an admin saves a folder with the rule "plain-claims" at severity error that avoids "we believe"
    Then the hand-written check is exactly as it was
    And a diff of the same folder lists the check as skipped because it is not drawn from these guidelines

  Scenario: Removing a rule file disables its check and leaves the others
    Given an admin saved a folder with the rule "plain-claims" at severity error that avoids "we believe" and the rule "short-leads" at severity warn with a pattern
    When an admin saves a folder with only the rule "short-leads" at severity warn with a pattern
    Then the check "publication#guideline-plain-claims" is disabled
    And the check "publication#guideline-short-leads" is enabled

  Scenario: The structured fields still give their checks
    When an admin saves the structured lexicon avoiding "synergy" through the console
    Then the check "publication#avoid-lexicon" exists with severity warn and the phrase "synergy"
