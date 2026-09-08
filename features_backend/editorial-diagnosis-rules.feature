@backend @editorial
Feature: Data-driven editorial rules for diagnose
  As a publication operator
  I want banned lists and patterns in the style profile
  So brochure-speak is flagged from data, and house-voice excerpts keep passing

  Scenario: Banned intensifiers come from the profile
    Given a style profile whose rules.bannedIntensifiers includes "seamless"
    And a draft that says "a seamless workflow for every team"
    When I run the diagnose command
    Then there is a finding whose excerpt includes "seamless"

  Scenario: Anth.us does not treat engineering vocabulary as insider terms
    Given the Anth.us style profile
    And a draft that says "Check latency in the repository" and does not use banned intensifiers
    When I run the diagnose command
    Then there is no rules finding for "latency" or "repository"

  Scenario: Must-fail brochure copy is caught
    Given a must-fail corpus draft that uses "revolutionary" and "coming soon"
    And the Anth.us style profile
    When I run the diagnose command
    Then findings include those banned terms

  Scenario: Must-pass house-voice excerpts are not flagged by rules
    Given the Anth.us style profile
    And a must-pass excerpt from an Anth.us reference sample
    When I run the diagnose command
    Then there are no findings produced by profile rules

  Scenario: Diagnose a text snippet without a draft file
    Given a loadable style profile
    When I run the diagnose command with --text "This seamless platform will revolutionize workflows" and no --draft
    Then it writes versioned diagnostic JSON
    And the result does not include rewritten prose
