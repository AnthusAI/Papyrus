@backend @monitoring-stories-queue
Feature: The daily monitor-stories run plans the day's drafting and a queue does it, one candidate at a time
  The daily run used to read the publication and then draft for as long as the Lambda's ten minutes lasted, and stopped on that time whether or not it had
  drafted anything useful; the next day it read everything again. Now the daily run is only the plan. It brings the vector index up to date with what changed,
  reads the publication once (the signals, the context packs, the candidates), and sends one message to the story queue for each step, best first. A worker
  drafts one step per invocation, each well inside the Lambda's limit, files what it keeps at once, and adds it to the plan's one review request. A step that
  fails is tried again by the queue and, after the last try, waits in a dead-letter queue that raises an alarm; the plan finishes without it. A Reference that was
  drafted is never planned again, one that was rejected waits for something new to be known about it, and a plan that is still running is not planned over.
  The model, the pages, the backends and the queue are fakes in these scenarios and nothing touches production.

  Background:
    Given a router with the publication "example-site", the story queue and no monitorStories setting

  Scenario: The daily run drafts nothing itself and queues one step for each candidate
    Given 3 accepted References for the queued run
    When the router plans its daily monitor stories
    Then no story draft is filed and the model is not asked
    And 3 steps are on the story queue, in the message group "example-site"
    And the log line for "example-site" says planned 3 steps and stoppedBy none

  Scenario: Every step is drafted by its own invocation and the plan ends with one review
    Given 3 accepted References for the queued run
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue
    Then 3 story drafts are filed by the workers, one per Reference
    And one soft review request holds the 3 ideas
    And the worker logs that the plan finished with 3 drafted and no failed step

  Scenario: A plan of many steps is drafted in full, each step by its own invocation
    Given 8 accepted References for the queued run
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue
    Then 8 story drafts are filed by the workers, one per Reference
    And the worker handled 8 steps, one invocation each, and logs that the plan finished with 8 drafted and no failed step

  Scenario: A step delivered twice is drafted once
    Given 2 accepted References for the queued run
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue
    And the story worker takes every step off the queue again
    Then 2 story drafts are filed by the workers, one per Reference
    And the model was asked to draft 2 stories in all

  Scenario: A step whose model call fails is delivered again and the other steps are not held up
    Given 2 accepted References for the queued run
    And the model fails on the first story
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue
    Then the queue is asked to deliver step 1 again and 1 story draft is filed
    When the model recovers and the story worker takes step 1 again
    Then 2 story drafts are filed by the workers, one per Reference
    And the worker logs that the plan finished with 2 drafted and no failed step

  Scenario: A step that fails its last try is parked and the plan still finishes
    Given 2 accepted References for the queued run
    And the model fails on the first story
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue on its last try
    Then the queue is asked to deliver step 1 again and 1 story draft is filed
    And the worker logs that the plan finished with 1 drafted and 1 failed step

  Scenario: The next day's run does not plan over a plan that is still running
    Given 2 accepted References for the queued run
    When the router plans its daily monitor stories
    And the router plans its daily monitor stories the next day
    Then the log line for "example-site" says the earlier plan is still being drafted
    And 2 steps are on the story queue, in the message group "example-site"

  Scenario: The next plan holds only what remains
    Given 3 accepted References for the queued run
    When the router plans its daily monitor stories
    And the story worker takes only the first step off the queue
    And the story worker takes every remaining step off the queue
    And a fourth accepted Reference arrives
    And the router plans its daily monitor stories the next day
    Then the second plan has 1 step

  Scenario: An idea is linked to its Reference even when the story index has not caught up
    Given the story index answers nothing for a story created a moment ago
    When an idea is filed for the Reference "reference-clef"
    Then the idea is filed and linked to "reference-clef" and no "No story found for lineage" error is raised

  Scenario: A step on a site with many other Items never lists them
    Given 3 accepted References for the queued run
    And the site holds 120 other Items in every stage, and refuses to list a table
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue and files for real
    Then 3 ideas are filed as Items at the idea stage
    And no step read a whole table
    And the worker logs that the plan finished with 3 drafted and no failed step

  Scenario: A step completes with a worker role that has no permission to list Items
    Given 2 accepted References for the queued run
    And the site holds 120 other Items in every stage, and refuses to list a table
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue and files for real
    Then every field the steps asked of the site is granted to the story worker's role
    And the story worker's role grants no listing of Items or of review requests

  Scenario: The plan reads the existing ideas once and shares them with its steps
    Given 2 accepted References for the queued run
    And the site holds 120 other Items in every stage, and refuses to list a table
    When the router plans its daily monitor stories
    And the story worker takes every step off the queue and files for real
    Then the plan's head row holds the existing ideas
    And no step asked for the site's stories by stage
