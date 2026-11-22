Feature: At the budget, paid agent work waits and says so
  Money is the one real limit on agent work. The owner sets the site's AI budget in the agent policy: an amount in dollars for each day, week or month,
  and one spend ledger counts what every paid run cost in the cycle. Before a paid run starts the runner reads the cycle total. At or over the budget the
  wake is not run and not lost: its run record says it is waiting, for the budget cycle, until the next cycle starts, and it keeps the wake so it can run
  then. The first wake that waits raises one flag for the admins; every later wake in the same cycle finds that flag and raises no other. When the cycle
  turns, one timer puts every waiting wake back on the site's queue in the order the wakes arrived, and each runs under its own key and its own run record.
  An admin who raises the budget releases them at once. A released wake re-checks the budget when it arrives, so a budget that is still too small leaves it
  waiting. Work whose definition is free never reads the budget, and reading, editing and serving never pass through the runner at all.

  Background:
    Given a site whose "rate" agent is at the rung "propose" with a budget of 5 dollars a week
    And the ledger holds 5 dollars of spend for the week of 2026-11-16
    And the runner's clock reads "2026-11-18T15:00:00Z"

  Scenario: At the budget a paid wake waits for the next cycle and keeps its wake
    When the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrives
    Then the rate procedure ran 0 times
    And the run record of "rate|schedule|2026-11-18T08:30:00Z" is waiting for "budget cycle" until "2026-11-23T00:00:00Z"
    And that run record keeps the wake "rate|schedule|2026-11-18T08:30:00Z" so it can run again
    And its line in the run list reads "‖ Waiting (budget cycle) until 2026-11-23T00:00:00Z"
    And the cycle's one timer is due at "2026-11-23T00:00:00Z"

  Scenario: A free check still runs at the budget
    Given the "rate" agent's registered definition says it is free
    When the wake "rate|schedule|2026-11-18T08:30:00Z" arrives
    Then the rate procedure ran 1 time
    And the run record of "rate|schedule|2026-11-18T08:30:00Z" is completed with the outcome "acted"
    And the admins were sent no budget flag

  Scenario: The flag is raised once in a cycle, however many wakes wait
    When the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrives
    And the paid wake "rate|schedule|2026-11-19T08:30:00Z" arrives
    And the paid wake "rate|schedule|2026-11-20T08:30:00Z" arrives
    Then the rate procedure ran 0 times
    And 3 run records are waiting for "budget cycle"
    And the admins have exactly one budget flag, "rr-budget-week-2026-11-16", saying the waiting work runs at "2026-11-23T00:00:00Z"
    And the cycle's one timer carries the wake "rate|schedule|2026-11-20T08:30:00Z" and is due at "2026-11-23T00:00:00Z"

  Scenario: The next cycle runs the waiting wakes in the order they arrived
    Given the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrived and waited
    And the paid wake "rate|schedule|2026-11-19T08:30:00Z" arrived and waited
    And the paid wake "rate|schedule|2026-11-20T08:30:00Z" arrived and waited
    When the runner's clock reads "2026-11-23T00:00:05Z" and the cycle's timer fires
    Then the rate procedure ran 0 times
    And the wake queue was given the released wakes "rate|schedule|2026-11-18T08:30:00Z, rate|schedule|2026-11-19T08:30:00Z, rate|schedule|2026-11-20T08:30:00Z" in that order
    When the wake queue delivers every released wake
    Then the rate procedure ran for "rate|schedule|2026-11-18T08:30:00Z, rate|schedule|2026-11-19T08:30:00Z, rate|schedule|2026-11-20T08:30:00Z" in that order
    And every one of those run records is completed with the outcome "acted"
    And no run record is waiting
    And the site keeps 3 run records in all

  Scenario: A wake delivered twice after its release runs once
    Given the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrived and waited
    When the runner's clock reads "2026-11-23T00:00:05Z" and the cycle's timer fires
    And the wake queue delivers every released wake
    And the cycle's timer message is delivered again
    Then the rate procedure ran 1 time
    And the site keeps 1 run record in all

  Scenario: Raising the budget releases the waiting wakes at once
    Given the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrived and waited
    And the paid wake "rate|schedule|2026-11-19T08:30:00Z" arrived and waited
    When an admin raises the site's budget to 20 dollars a week because "Launch week" and applies it
    Then the agent policy holds a budget of 20 dollars a week
    And the wake queue was given the released wakes "rate|schedule|2026-11-18T08:30:00Z, rate|schedule|2026-11-19T08:30:00Z" in that order
    When the wake queue delivers every released wake
    Then the rate procedure ran for "rate|schedule|2026-11-18T08:30:00Z, rate|schedule|2026-11-19T08:30:00Z" in that order
    And no run record is waiting

  Scenario: A budget that is still reached leaves the released wakes waiting, and none is lost
    Given the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrived and waited
    When an admin raises the site's budget to 5 dollars a week because "Release what fits" and applies it
    And the wake queue delivers every released wake
    Then the rate procedure ran 0 times
    And the run record of "rate|schedule|2026-11-18T08:30:00Z" is waiting for "budget cycle" until "2026-11-23T00:00:00Z"
    And the admins have exactly one budget flag, "rr-budget-week-2026-11-16", saying the waiting work runs at "2026-11-23T00:00:00Z"

  Scenario: The budget is a person's to raise, never an agent's
    Given the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrived and waited
    When an agent raises the site's budget to 20 dollars a week because "More room" and applies it
    Then the budget command is refused as "blocked"
    And the agent policy holds a budget of 5 dollars a week
    And the wake queue was given no released wake

  Scenario: A dry run of raising the budget names the waiting wakes and changes nothing
    Given the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrived and waited
    When an admin raises the site's budget to 20 dollars a week because "Launch week" as a dry run
    Then the dry run names the waiting wake "rate|schedule|2026-11-18T08:30:00Z"
    And the agent policy holds a budget of 5 dollars a week
    And the wake queue was given no released wake

  Scenario: Every request the spend stop sends is one the site's GraphQL schema accepts
    Given the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrived and waited
    When an admin raises the site's budget to 20 dollars a week because "Launch week" and applies it
    And the wake queue delivers every released wake
    Then the spend stop's writes and its read of the waiting runs are accepted by the GraphQL schema Amplify generates from the data schema
