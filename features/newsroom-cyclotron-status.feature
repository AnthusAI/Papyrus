Feature: The References tab shows what the relevance cyclotron is doing
  Above the references, a strip says the cyclotron's version, agreement,
  calibration and review rate in words. The detail card explains each number.
  Editors who may change the review rate can ask the next sweep for a manual
  rate with an expiry.

  @brand-agnostic
  Scenario: An editor reads the status strip and opens the detail
    Given I open the references newsroom at 1280 by 900
    Then the cyclotron status strip should say "Onboarding · 100% reviewed"
    When I open what the cyclotron is doing
    Then the cyclotron card should be titled "Relevant to this publication"
    And the cyclotron card should explain "Of all items, how many it got right."
    And no browser console errors should occur

  @brand-agnostic
  Scenario: An editor asks for a manual review rate
    Given I open the references newsroom at 1280 by 900
    When I open what the cyclotron is doing
    And I ask for a manual review rate of "25%" for "7 days"
    Then the review rate form should say the next sweep applies it
