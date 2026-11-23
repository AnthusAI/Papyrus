@backend @newsroom
Feature: An unusually costly run is flagged from the agent's own history, and never stopped
  The site's budget is the one limit on what agent work spends. Inside it, cost is never a reason to stop a run: a run that costs far more than
  the agent usually spends is something a person should look at, so it raises a flag with the numbers and the run goes on as it would have.

  "Far more than usual" is learned from the agent itself, not set as a dollar figure. Every finished run whose calls all had a price joins its
  agent's history in the spend ledger, once, however often its wake is delivered. A new run is compared with the agent's earlier runs on the
  logarithm of their cost, because cost grows by multiplying (more input, more calls, longer answers): it is unusual when it lands above the
  prediction bound for one more run from that history, which a run from the same history passes only one time in a thousand. The bound is wider
  when the history is short, and an agent with fewer than two earlier priced runs has no spread to compare with, so its run is not judged and the
  judgement says why instead of guessing.

  The owner may also give an agent a budget per run in the agent policy. It is a figure for a person, not a limit: a run over it raises the same
  one flag, saying so, and is not stopped. Only an admin who is a person sets it.

  Background:
    Given a site whose "rate" agent is at the rung "propose" with a budget of 100 dollars a week
    And the runner's clock reads "2026-11-18T15:00:00Z"

  Scenario: A run within the agent's history raises nothing
    Given the "rate" agent's last 20 runs cost between 1.0 and 1.6 cents each
    When the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrives and its run costs 1.4 cents
    Then the rate procedure ran 1 time
    And the cost of that run was judged against 20 earlier runs and is not unusual
    And the admins were sent no cost flag
    And the "rate" agent's history holds 21 runs

  Scenario: A run far above the agent's history raises one flag with the figures and is not stopped
    Given the "rate" agent's last 20 runs cost between 1.0 and 1.6 cents each
    When the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrives and its run costs 40 cents
    Then the rate procedure ran 1 time
    And the run record of "rate|schedule|2026-11-18T08:30:00Z" is completed with the outcome "acted"
    And the admins have exactly one cost flag, for the run of "rate|schedule|2026-11-18T08:30:00Z"
    And the flag says the run cost "$0.4000" against "20 earlier runs", with what such a run typically costs and the cost passed one time in 1,000
    And the flag says the run was not stopped
    And the "rate" agent's history holds 21 runs

  Scenario: A wake delivered again after its spend was counted adds nothing and raises no second flag
    Given the "rate" agent's last 20 runs cost between 1.0 and 1.6 cents each
    When the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrives and its run costs 40 cents
    And the same run's spend is recorded again, as a redelivered wake would
    Then the admins have exactly one cost flag, for the run of "rate|schedule|2026-11-18T08:30:00Z"
    And the "rate" agent's history holds 21 runs
    And the site's ledger counted that run once

  Scenario: An agent with little history says so instead of guessing
    Given the "rate" agent's last 1 run cost 1.2 cents
    When the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrives and its run costs 40 cents
    Then the rate procedure ran 1 time
    And the cost of that run was not judged, because "The agent has 1 earlier priced run; at least 2 are needed to tell whether a cost is unusual"
    And the admins were sent no cost flag
    And the "rate" agent's history holds 2 runs

  Scenario: A run over the owner's budget per run raises one flag and is not stopped
    Given the "rate" agent's last 20 runs cost between 1.0 and 1.6 cents each
    And an admin sets the "rate" agent's budget per run to 0.01 dollars because "Rating should stay cheap" and applies it
    When the paid wake "rate|schedule|2026-11-18T08:30:00Z" arrives and its run costs 1.4 cents
    Then the rate procedure ran 1 time
    And the run record of "rate|schedule|2026-11-18T08:30:00Z" is completed with the outcome "acted"
    And the admins have exactly one cost flag, for the run of "rate|schedule|2026-11-18T08:30:00Z"
    And the flag says the run is over the owner's budget of "$0.0100" per run
    And the flag says the run was not stopped

  Scenario: The budget per run is a person's to set, never an agent's
    When an agent sets the "rate" agent's budget per run to 5 dollars because "More room" and applies it
    Then the budget command is refused as "blocked"
    And the agent policy holds no budget per run for the "rate" agent
