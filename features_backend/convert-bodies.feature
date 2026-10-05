Feature: Converting legacy body paragraphs to Markus
  A one-time command turns the legacy body[] paragraph list into a Markus body
  and its stored IR, and refuses to write anything it cannot convert losslessly.

  Scenario: Converting an article with a plain paragraph body preserves its text
    Given an article whose body paragraphs are "Cats & dogs: *stars*" and "# not a heading"
    When I convert the bodies and apply the changes
    Then the article is converted
    And the stored Markus body escapes the special characters
    And the stored IR paragraphs are "Cats & dogs: *stars*" and "# not a heading"

  Scenario: A paragraph that cannot be converted losslessly is reported and skipped
    Given an article whose body paragraphs are "Fish &amp; chips"
    When I convert the bodies and apply the changes
    Then the article is reported as "skipped:not-lossless"
    And nothing is written
