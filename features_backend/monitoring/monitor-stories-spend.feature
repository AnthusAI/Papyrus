@backend @monitoring-stories-queue
Feature: Monitor stories spend the site's money like any other agent work: counted, limited by the budget, and flagged when unusual
  The daily monitor-stories job runs in the monitoring router, not in the procedure runner, so until now it had its own fixed ceilings of fifty cents a
  publication and fifty cents a step, and its spend was in no ledger: it did not count against the site's budget and no one was told when it cost more than
  usual. Now it goes through the same three things as every other paid agent run.

  Before paid work starts the spend brake is asked: the daily plan of a publication asks before its vector pass (embeddings cost money), and each queued
  step asks again before it drafts. A halted site starts nothing. At the site's budget nothing paid starts either; the work waits for the next budget cycle
  and the admins get the cycle's one flag, the same flag the runner's waiting work raises. Nothing waits on a queue to be lost: a candidate that was not
  drafted is not marked drafted or rejected, so the first daily plan under the budget plans it again.

  After paid work its model calls and cost go into the spend ledger, once, however often a step's message is delivered: the site's total, which the budget
  limits, and the agent's own. Drafting is the "monitor_stories" agent (one queued step is one run) and the vector pass is "monitor_stories_index" (one plan's
  pass is one run), because their costs differ by orders of magnitude. A run whose every call had a price joins its agent's cost history and is judged
  against it: an unusual cost raises one flag and stops nothing. There is no fixed cost ceiling any more; the site's budget is the one limit.

  The site is the router publication's tenant, and its budget and agent settings are read from its agent policy in its site bucket, as the runner reads
  them. A publication whose router entry names neither cannot be counted, so its monitor stories do not start and say why.

  The model, the pages, the backends, the ledger table and the queue are fakes in these scenarios and nothing touches production.

  Background:
    Given a router with the publication "example-site", the story queue and no monitorStories setting

  Scenario: Each drafted step is one run of the monitor_stories agent, counted once however often it is delivered
    Given 2 accepted References for the queued run
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue
    And the story worker takes every step off the queue again
    Then 2 story drafts are filed by the workers, one per Reference
    And the site's spend this month holds the model calls and the cost of the 2 drafted steps, each counted once
    And the "monitor_stories" agent's cost history holds 2 runs

  Scenario: No cost ceiling stops a step: a step that costs more than fifty cents is drafted and filed
    Given 1 accepted References for the queued run
    And every model call reports 3000000 input tokens
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue
    Then 1 story drafts are filed by the workers, one per Reference
    And the "monitor_stories" agent's spend this month is more than 0.50 dollars

  Scenario: A step that costs far more than the agent's history raises one cost flag, and its idea is still filed
    Given the "monitor_stories" agent's last 20 runs on the site cost between 0.10 and 0.16 cents each
    And 1 accepted References for the queued run
    And every model call reports 3000000 input tokens
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue
    Then 1 story drafts are filed by the workers, one per Reference
    And the admins have exactly one cost flag, and it says the run was not stopped
    And the "monitor_stories" agent's cost history holds 21 runs

  Scenario: At the site's budget the daily plan waits, queues nothing and tells the admins once
    Given 2 accepted References for the queued run
    And the site has spent its budget of 100 dollars for this month
    When the router plans its daily monitor stories
    And the router plans its daily monitor stories the next day
    Then nothing is on the story queue and the model is not asked
    And the log line for "example-site" says it waits for the budget cycle until "2026-11-01T00:00:00Z"
    And the admins have exactly one budget flag, for the month that started on "2026-10-01"

  Scenario: A step that finds the budget reached waits, and the first plan of the next cycle drafts what it left
    Given 2 accepted References for the queued run
    When the router plans its daily monitor stories
    And the site has spent its budget of 100 dollars for this month
    And the story worker takes every step off the queue
    Then no story draft is filed and the model is not asked
    And every step logs that it waits for the budget cycle
    And the worker logs that the plan finished with 0 drafted and 2 steps held back by "budget_reached"
    And no curation flag is raised
    When the month turns and the router plans its daily monitor stories
    And the story worker takes every step of that plan off the queue
    Then 2 story drafts are filed by the workers, one per Reference

  Scenario: A halted site starts no monitor stories
    Given 2 accepted References for the queued run
    And runs are halted for the site because "Spend is being investigated"
    When the router plans its daily monitor stories
    Then nothing is on the story queue and the model is not asked
    And the log line for "example-site" says monitor stories did not start because "halted"

  Scenario: The plan's vector pass is one run of the monitor_stories_index agent
    Given 2 accepted References for the queued run
    And a vector pass that makes 4 embedding requests costing 0.0004 dollars
    When the router plans its daily monitor stories
    Then the "monitor_stories_index" agent's spend this month is 4 calls and 0.0004 dollars
    And the site's spend this month includes the vector pass

  Scenario: A publication whose router entry names no tenant or site bucket starts no monitor stories, and says why
    Given 2 accepted References for the queued run
    And the router reads each publication's site and policy from its router entry, as the Lambda does
    When the router plans its daily monitor stories
    Then nothing is on the story queue and the model is not asked
    And the log line for "example-site" names the missing "tenantId" and "siteBucket" as why monitor stories did not start, with the code "not_located"
