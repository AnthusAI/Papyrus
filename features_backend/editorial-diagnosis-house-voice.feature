@backend @editorial
Feature: Diagnose respects house voice and optional checks
  As a publication operator
  I want diagnose findings I can actually steer
  So recent Anth.us articles are not a pile of cadence and never-word false positives

  Scenario: Always-on is not unsupported certainty
    Given a draft containing "Keep always-on rules thin" and "Grok Bot is always-available"
    And a loadable style profile
    When I run the diagnose command
    Then there is no unsupported_certainty finding whose excerpt is only those compounds

  Scenario: List ordinals are not missing attribution
    Given a draft whose only numbers are markdown list markers 1. and 2.
    When I run the diagnose command
    Then there is no missing_attribution finding for those markers

  Scenario: Anth.us profile does not flag punchy cadence as slop
    Given the Anth.us style profile with uniform cadence disabled
    And a draft of five consecutive short punchy sentences
    When I run the diagnose command
    Then there is no uniform_cadence finding

  Scenario: Brochure slop still fires
    Given a draft that says "This will revolutionize workflows" and "Everyone knows agents will transform the industry"
    When I run the diagnose command
    Then findings include vague_claim or voice_mismatch for the avoided lexicon
    And findings include unsupported_certainty for "Everyone knows"

  Scenario: Rhetorical refrain is not redundancy
    Given a draft that repeats a short heading "It did not manage it" as a refrain
    When I run the diagnose command
    Then that refrain is not a redundancy group
