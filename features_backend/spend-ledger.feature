@backend @newsroom
Feature: One spend ledger counts every paid run once (slice G1, PPY-fa165c)
  A finished run that called a model adds its cost to the site's counter and to its agent's counter for the budget cycle it finished in. The cycle is the budget
  period of the site's agent policy: a day, a week (Monday to Sunday) or a month. The ledger holds numbers only, in millionths of a dollar, and counts a run once however
  many times its wake is delivered. A model call with no price is counted as an unpriced call and never as free, so a cycle that has any is partial.

  Scenario: A finished run adds its cost to the site and to its agent
    Given an empty spend ledger and a site whose budget period is "week"
    When the run "run-1" of the agent "rate" finishes on Wednesday 18 November 2026 with 3 priced calls costing 0.012 dollars
    Then the site's cycle starting Monday 16 November 2026 holds 0.012 dollars from 3 calls
    And the agent "rate" cycle starting Monday 16 November 2026 holds 0.012 dollars from 3 calls

  Scenario: A redelivered wake does not add twice
    Given an empty spend ledger and a site whose budget period is "week"
    When the run "run-1" of the agent "rate" finishes on Wednesday 18 November 2026 with 3 priced calls costing 0.012 dollars
    And the same wake is delivered again and the run is counted again
    Then the site's cycle starting Monday 16 November 2026 holds 0.012 dollars from 3 calls
    And the second delivery added nothing

  Scenario: A run with an unpriced model marks the total partial
    Given an empty spend ledger and a site whose budget period is "month"
    When the run "run-2" of the agent "rate" finishes on Wednesday 18 November 2026 with 4 calls, 1 of them unpriced, costing 0.009 dollars
    Then the site's cycle starting Sunday 1 November 2026 holds 0.009 dollars from 4 calls
    And the site's total is partial, missing 1 call

  Scenario: Runs of different cycles are counted apart
    Given an empty spend ledger and a site whose budget period is "week"
    When the run "run-1" of the agent "rate" finishes on Wednesday 18 November 2026 with 3 priced calls costing 0.012 dollars
    And the run "run-3" of the agent "rate" finishes on Monday 23 November 2026 with 2 priced calls costing 0.004 dollars
    Then the site's cycle starting Monday 16 November 2026 holds 0.012 dollars from 3 calls
    And the site's cycle starting Monday 23 November 2026 holds 0.004 dollars from 2 calls

  Scenario: The X account's spend is counted in the same ledger, by its own billing cycle
    Given an empty spend ledger and a site whose budget period is "week"
    When Caducus charges the X account "mom" 0.20 dollars on Wednesday 18 November 2026 in the cycle starting Sunday 1 November 2026
    And Caducus charges the X account "mom" 0.20 dollars on Thursday 19 November 2026 in the cycle starting Sunday 1 November 2026
    Then the X account "mom" cycle starting Sunday 1 November 2026 holds 0.40 dollars
    And the X account "mom" cycle starting Sunday 1 December 2026 holds nothing

  Scenario: X spend and AI spend do not mix
    Given an empty spend ledger and a site whose budget period is "month"
    When the run "run-1" of the agent "rate" finishes on Wednesday 18 November 2026 with 3 priced calls costing 0.012 dollars
    And Caducus charges the X account "mom" 0.20 dollars on Wednesday 18 November 2026 in the cycle starting Sunday 1 November 2026
    Then the site's cycle starting Sunday 1 November 2026 holds 0.012 dollars from 3 calls
    And the X account "mom" cycle starting Sunday 1 November 2026 holds 0.20 dollars
