Feature: Every change to a Story or its checklist wakes the agents that listen for it, once
  A DynamoDB stream on the Item table invokes a small feed function (PPY-8a374e, slice B2 of the always-on agents design). Whoever wrote the change (the console
  board, the command line, an agent, a person's save) the stream record is the same, so the feed starts procedures for all of them and no writer has to call
  anything. For each record the feed normalizes the change: a Story version created, a Story entering a stage (a first version created at a stage, or the stage
  field changed in place, as a board move does), a checklist step getting a new state, or a Story's star rating being set, changed or cleared in place (PPY-e3bb2b).
  A note on a step, a version being marked superseded, a card's counts being refreshed and a new version that only carries the rating over are no change. It then puts one wake on the site's wake queue for each agent that listens for that change, found in the site's listener index:
  one small document, written by the deploy from the registered definitions, read by its live version. The feed never lists the Automation table or any other
  table. The wake key is the agent, the Story's lineage, the version and what changed; the run record made from it is the claim, and the queue's message group is
  the agent plus the Story, so one Story's wakes for an agent run one after the other. An agent's own change never wakes that agent. The wake carries whether the
  step is paid, who made the change and when, which is what the wake gate reads: the quiet window for paid steps (coalescing-window.feature) and the loop guard
  (agent-loop-guard.feature). The scenarios below run the feed with no gate, so every wake goes on the queue at once.

  Background:
    Given the site "sample" with its wake queue and its listener index
    And these agents listen
      | agent         | procedure          | paid  | change        | filter                 |
      | stage-copy    | story.copy_edit    | true  | stage_entered | stage=copywriting      |
      | sources-check | story.sources      | false | version_created | type=story           |
      | fact-check    | story.fact_check   | true  | version_created | type=story           |
      | illustrate    | story.illustrate   | true  | step_changed  | step=illustration,state=open |
      | rating-watch  | story.rating_watch | false | rated         | stage=published      |

  Scenario: A console board move wakes the agent for the stage
    When a person moves the Story "story-1" to "copywriting" in the console board
    Then the queue holds 1 wake, for the agent "stage-copy"
    And the wake key is "stage-copy|story-1|story-1-v3|stage_entered.copywriting"
    And the wake says the Story entered copywriting and who moved it
    And the wake is in the message group of "stage-copy" and "story-1"

  Scenario: A move to a stage nobody listens for sends nothing
    When a person moves the Story "story-1" to "typesetting" in the console board
    Then the queue holds 0 wakes

  Scenario: A new version wakes each listening step once
    When a person saves version 4 of the Story "story-1"
    Then the queue holds 2 wakes, for the agents "fact-check" and "sources-check"
    And the wake for "fact-check" says the step is paid
    And the wake for "sources-check" says the step is free
    And each wake names the person who saved the version and when

  Scenario: A command-line write wakes the listening agents the same way
    When the command line saves version 4 of the Story "story-1" as a person
    Then the queue holds 2 wakes, for the agents "fact-check" and "sources-check"

  Scenario: A redelivered stream record starts nothing twice
    When a person saves version 4 of the Story "story-1"
    And the same stream record is delivered again inside the queue's window
    Then the queue holds 2 wakes, for the agents "fact-check" and "sources-check"
    When the same stream record is delivered again after the queue's window
    And the runner takes every wake on the queue
    Then the site has 2 run records, one for each wake key
    And each agent's procedure ran once

  Scenario: An agent's own version does not wake that agent
    When the agent "fact-check" saves version 4 of the Story "story-1"
    Then the queue holds 1 wake, for the agent "sources-check"
    And no wake is for the agent "fact-check"

  Scenario: An agent's own stage move does not wake that agent
    When the agent "stage-copy" moves the Story "story-1" to "copywriting"
    Then the queue holds 0 wakes

  Scenario: Another agent's change wakes the agent
    When the agent "sources-check" moves the Story "story-1" to "copywriting"
    Then the queue holds 1 wake, for the agent "stage-copy"
    And the wake says the change was made by an agent

  Scenario: A checklist step changing state wakes the agent that listens for that step
    When a person reopens the step "illustration" of the Story "story-1"
    Then the queue holds 1 wake, for the agent "illustrate"
    And the wake key names the Story and the step's version

  Scenario: A note on a step is no change
    When a person adds a note to the step "illustration" of the Story "story-1"
    Then the queue holds 0 wakes

  Scenario: Book-keeping writes on a Story are no change
    When the table marks the previous version of the Story "story-1" superseded
    And the table refreshes the checklist counts on the Story "story-1"
    Then the queue holds 0 wakes
    And the listener index was not read

  Scenario: A rating made in place wakes the agent that listens for ratings, once
    When a person rates the published Story "story-1" 4 stars
    Then the queue holds 1 wake, for the agent "rating-watch"
    And the wake key is "rating-watch|story-1|story-1-v3|rated.4.2026-11-18T12:00:00Z"
    And the wake says the Story was rated 4 stars by a person

  Scenario: Rating the same Story again is a new wake, and a redelivered record is the same one
    When a person rates the published Story "story-1" 4 stars
    And a person rates the published Story "story-1" 3 stars
    Then the queue holds 2 wakes, for the agents "rating-watch" and "rating-watch"
    When the same stream record is delivered again inside the queue's window
    Then the queue holds 2 wakes, for the agents "rating-watch" and "rating-watch"

  Scenario: Clearing a rating is a change the agent hears
    When a person clears the rating of the published Story "story-1"
    Then the queue holds 1 wake, for the agent "rating-watch"
    And the wake says the Story was left unrated

  Scenario: A rating on a Story that is not published does not wake an agent that listens for published Stories
    When a person rates the Story "story-1" 4 stars while it is in "copywriting"
    Then the queue holds 0 wakes

  Scenario: A new version that only carries the rating over is no rating
    When a person saves version 4 of the Story "story-1" carrying its rating of 4 stars over
    Then the queue holds 0 wakes for the agent "rating-watch"

  Scenario: A change nobody listens for sends nothing
    When a person saves version 4 of the Story "story-1" with the type "wiki_page"
    Then the queue holds 0 wakes

  Scenario: A site whose deploy has written no listener index has no listeners
    Given the site has no listener index
    When a person saves version 4 of the Story "story-1"
    Then the queue holds 0 wakes
    And the Automation table was not listed

  Scenario: A change never lists the Automation table or any table
    When a person saves version 4 of the Story "story-1"
    And a person moves the Story "story-1" to "copywriting" in the console board
    Then the queue holds 3 wakes
    And no table was listed or scanned
    And the feed's code has no list of the Automation table

  Scenario: The index is read again only when the deploy moves it
    When a person saves version 4 of the Story "story-1"
    And a person saves version 5 of the Story "story-1"
    Then the listener index body was fetched once
    When the deploy writes a changed listener index
    And a person saves version 6 of the Story "story-1"
    Then the listener index body was fetched twice

  Scenario: A wake that cannot be sent fails its record, and the retry sends only what is missing
    Given the queue refuses the second wake it is given
    When a person saves version 4 of the Story "story-1"
    Then the batch reports the record as failed
    When the queue accepts wakes again and the batch is retried
    Then the queue holds 2 wakes, for the agents "fact-check" and "sources-check"

  Scenario: A row of another tenant is nobody's wake
    When a person saves version 4 of a Story that belongs to the tenant "beta"
    Then the queue holds 0 wakes
    And the listener index was not read

  Scenario: A removed row is no change
    When the table removes a version of the Story "story-1"
    Then the queue holds 0 wakes

  Scenario: The deploy writes the listener index from the registered definitions
    Given the definitions "stage-copy" and "fact-check" in Git
    When the deploy writes the listener index
    Then the site's listener index is version 1 and lists "stage-copy" under stage_entered and "fact-check" under version_created
    When the deploy writes the listener index again with the same definitions
    Then no new version is written
    When the definition "fact-check" is removed from Git and the deploy writes the listener index
    Then the site's listener index is version 2 and no longer lists "fact-check"
    And the listener index holds no rung, pause or budget
