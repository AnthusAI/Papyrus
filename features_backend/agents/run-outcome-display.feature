@backend @newsroom
Feature: The console shows a run's outcome as an icon and its words
  The command line shows an outcome as a text mark and its words (a check, a dash, a question mark, a cross, an exclamation mark). The console never shows
  those text marks: it shows a Lucide icon of a different shape for each outcome, beside the words, so the five tell apart without colour. The
  procedure's Recent Runs panel reads each run's own record, and shows the same icon and the same words the command line shows for that run.

  Scenario: Each outcome shows a distinct icon and its words
    Given the server's outcome lines for acted, nothing, asked, failed and unknown
    When the console renders each outcome
    Then each outcome shows an icon and its words
    And no outcome shows the command line's text mark

  Scenario: Outcomes are distinguishable without colour
    Given the server's outcome lines for acted, nothing, asked, failed and unknown
    When the console renders each outcome
    Then the five icons have five different shapes

  Scenario: The procedure's Recent Runs panel shows each run's outcome as an icon and its words
    Given a procedure's recent runs that did it, had nothing to do, asked, failed, have an unknown outcome, wait for the budget cycle, are not finished and were recorded before outcomes
    When the console renders the procedure's Recent Runs panel
    Then each run shows an icon and the words the command line shows for that run, without the text mark
    And the five outcomes have five different shapes in the panel too
