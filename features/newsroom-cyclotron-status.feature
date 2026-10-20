Feature: The References tab shows how well suggestions are doing
  Above the references, a strip says how suggestions are doing in words.
  The detail card explains each number. Editors who may change the review
  rate can ask for a manual rate with an expiry.

  @brand-agnostic
  Scenario: An editor reads the status strip and opens the detail
    Given I open the references newsroom at 1280 by 900
    Then the suggestion status strip should say "Onboarding · 100% reviewed"
    When I open the suggestion details
    Then the suggestion details card should be titled "Relevant to this publication"
    And the suggestion details card should explain "Of all items, how many it got right."
    And no browser console errors should occur

  @brand-agnostic
  Scenario: An editor asks for a manual review rate
    Given I open the references newsroom at 1280 by 900
    When I open the suggestion details
    And I ask for a manual review rate of "25%" for "7 days"
    Then the review rate form should confirm the rate was saved
