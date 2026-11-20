@backend @newsroom
Feature: The console shows a run's outcome as an icon and its words (PPY-1a322a)
  The command line shows an outcome as a text mark and its words (a check, a dash, a question mark, a cross, an exclamation mark). The console never shows
  those text marks: it shows a Lucide icon of a different shape for each outcome, beside the words, so the five tell apart without colour.

  Scenario: Each outcome shows a distinct icon and its words
    Given the server's outcome lines for acted, nothing, asked, failed and unknown
    When the console renders each outcome
    Then each outcome shows an icon and its words
    And no outcome shows the command line's text mark

  Scenario: Outcomes are distinguishable without colour
    Given the server's outcome lines for acted, nothing, asked, failed and unknown
    When the console renders each outcome
    Then the five icons have five different shapes
