Feature: An Assignment is the request one responsibility makes of another
  When one agent needs another's work (the fact-checker needs a source found), it asks for it as an Assignment on the Story, through the gate.
  The Assignment says who asked and why. The agent responsible for that kind of work is woken once, by the change feed: the wake
  key names the Assignment, so the run record made from it is the claim and the agent runs once however many times the stream record is delivered. When the run
  ends, the Assignment closes: completed, with the run's result recorded on the Story's Assignment, which wakes the agent that asked and no other; or failed, with
  the error recorded and one flag raised for a person. Nothing retries a failed Assignment: a person reopens it, which is a new wake. A person files the same
  record with the same command, and nobody is woken when it completes, because the Story shows the result. An Assignment is never a Message: no Message is
  written by the request, and nothing is sent between agents.

  Background:
    Given the site "sample" with its wake queue and its listener index
    And these agents listen for changes
      | agent      | procedure          | paid  | kind       | change    | filter                |
      | research   | research.run       | false | Assignment | created   | responsibility=research |
      | research   | research.run       | false | Assignment | reopened  | responsibility=research |
      | fact_check | story.fact_check   | true  | Assignment | completed | responsibility=research |
    And these responsibilities are at these rungs
      | responsibility | rung    |
      | fact_check     | propose |
      | research       | draft   |
      | observer       | observe |

  Scenario: An agent's request appears on the Story with who asked and why
    When the agent "fact_check" asks "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    Then the request is accepted and wrote a new Assignment
    And the Story "story-1" has 1 Assignment for "research", open, asked by "agent:fact_check" for this reason: "Claim 3 cites no source. Find one."
    And the Assignment has a created event by "agent:fact_check"
    And the request wrote no Message

  Scenario: The responsible agent is woken once and runs once
    Given the agent "fact_check" asked "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    When the Assignment stream is delivered to the change feed
    And the same Assignment stream records are delivered again
    Then the queue holds 1 wake, for the agent "research"
    And the wake key for "research" names the Assignment and is "created"
    And the wake for "research" carries who asked and why
    When the runner takes the wake for "research"
    And the queue delivers that wake to the runner again
    Then the responsible procedure ran 1 time
    And the second delivery is recognised as a duplicate
    And the Assignment was claimed by "research" while the run was in hand

  Scenario: Completion writes the result on the Story and wakes the agent that asked
    Given the agent "fact_check" asked "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    And the procedure ends having found "Found two primary sources"
    When the Assignment stream is delivered to the change feed
    And the runner takes the wake for "research"
    Then the responsible run ended "acted"
    And the handoff Assignment is completed
    And the completion on the Story records the run, its outcome "acted" and the result "Found two primary sources"
    When the Assignment stream is delivered to the change feed
    Then the queue holds 1 wake, for the agent "fact_check"
    And the wake key for "fact_check" names the Assignment and is "completed."

  Scenario: A person files the same request, and nobody is woken when it completes
    Given a person asked "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    When the Assignment stream is delivered to the change feed
    Then the queue holds 1 wake, for the agent "research"
    And the Story "story-1" has 1 Assignment for "research", open, asked by "ada" for this reason: "Claim 3 cites no source. Find one."
    When the runner takes the wake for "research"
    And the Assignment stream is delivered to the change feed
    Then the handoff Assignment is completed
    And the queue holds 0 wakes

  Scenario: An agent that asks the same thing again gets the Assignment it made
    Given the agent "fact_check" asked "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    When the agent "fact_check" asks "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    Then the request is accepted and wrote nothing new
    And the Story "story-1" has 1 Assignments for "research"

  Scenario: A person who asks again files a new request
    Given a person asked "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    When a person asks "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    Then the request is accepted and wrote a new Assignment
    And the Story "story-1" has 2 Assignments for "research"

  Scenario: A failed Assignment is recorded, raises one flag and is not retried by itself
    Given the agent "fact_check" asked "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    And the procedure fails with "the source site refused the request"
    When the Assignment stream is delivered to the change feed
    And the runner takes the wake for "research"
    Then the responsible run ended "failed"
    And the handoff Assignment is failed
    And the failure on the Assignment records the error "the source site refused the request"
    And exactly 1 flag is raised for a person about the Assignment
    When the Assignment stream is delivered to the change feed
    And the same Assignment stream records are delivered again
    Then the stream makes no wake and nothing starts the work again
    And the responsible procedure ran 1 time

  Scenario: A person reopens a failed Assignment, which is a new wake
    Given the agent "fact_check" asked "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    And the procedure fails with "the source site refused the request"
    When the Assignment stream is delivered to the change feed
    And the runner takes the wake for "research"
    And the Assignment stream is delivered to the change feed
    And a person reopens the Assignment
    And the Assignment stream is delivered to the change feed
    Then the queue holds 1 wake, for the agent "research"
    And the wake key for "research" names the Assignment and is "reopened."

  Scenario: A run that asks a person leaves the Assignment in hand
    Given the agent "fact_check" asked "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    And the procedure ends asking a person about "needs_choice"
    When the Assignment stream is delivered to the change feed
    And the runner takes the wake for "research"
    Then the responsible run ended "asked"
    And the handoff Assignment is claimed
    And exactly 0 flag is raised for a person about the Assignment

  Scenario: A request for work nobody listens for waits open and wakes nobody
    When the agent "fact_check" asks "illustrate" for work on the Story "story-1" because "Section 3 needs a figure."
    And the Assignment stream is delivered to the change feed
    Then the Story "story-1" has 1 Assignment for "illustrate", open, asked by "agent:fact_check" for this reason: "Section 3 needs a figure."
    And the queue holds 0 wakes

  Scenario: An agent whose rung does not allow asking is stopped by the gate
    When the agent "observer" asks "research" for work on the Story "story-1" because "Claim 3 cites no source. Find one."
    Then the request is refused as "human_required"
    And the request wrote nothing

  Scenario: An agent does not ask itself
    When the agent "research" asks "research" for work on the Story "story-1" because "Find more."
    Then the request is refused as "constraint_conflict"
    And the request wrote nothing

  Scenario: A request about a Story that does not exist is refused
    When the agent "fact_check" asks "research" for work on the Story "no-such-story" because "Find one."
    Then the request is refused as "not_found"
    And the request wrote nothing

  Scenario: Other kinds of Assignment are not requests between agents
    Given the Assignment of another kind "research.candidate" is in the site
    When the Assignment stream is delivered to the change feed
    Then the queue holds 0 wakes
