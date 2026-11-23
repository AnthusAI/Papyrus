@backend @agents
Feature: A person's answer to an agent's question wakes that agent, and the work goes on or stops
  An agent that needs a person's leave does not wait for it. Its run asks the one gate, the gate says a person must do or approve the operation, one
  review request is filed on the run, naming the run and the agent, and the run ends "asked". Nothing is held open. When a person answers, the answer
  is a change to the review request, and the change feed wakes the agent that asked and no other. The run that wakes reads the request and the run
  that asked again, from the records. An approval lets the new run do what the person approved, once: the gate records the approval and the request
  it came from, and the request names the run that used it. A rejection runs nothing: the run ends "nothing to do" with the person's reason. Feedback
  is given to the next run as its input, and approves nothing. While one request waits, the same agent goes on with every other Story.

  Background:
    Given the site "sample" with its wake queue and its listener index
    And the agent "illustrate" runs "story.illustrate" when a Story enters "illustration" and when a review request it raised is answered
    And the site's policy puts "illustrate" at the rung "propose"
    And the agent's procedure asks the gate for "image_apply"

  Scenario: A run that needs a person's leave asks once and ends
    When a person moves the Story "story-1" into "illustration"
    And the runner takes the agent's wake for the Story "story-1"
    Then the agent's run ended "asked" with the reason "human_required"
    And the agent has 1 review request, open, about that run, raised by "agent:illustrate"
    And the queue holds 0 wakes

  Scenario: An approval wakes the agent that asked, and the work completes once
    Given the agent asked a person about the Story "story-1"
    When a person approves the agent's review request
    And the review request stream reaches the change feed
    Then the queue holds 1 wake, for the agent "illustrate"
    When the runner takes the agent's wake for the answer
    Then the agent's run ended "acted"
    And the gate allowed "image_apply" for that run because the person approved it in the review request
    And the agent has 1 review request
    And the review request names that run as the one that used the answer
    When the same review request stream records reach the change feed again
    And the queue delivers the answer's wake to the runner again
    Then the second delivery of the answer's wake is a duplicate
    And the agent's procedure ran 2 times

  Scenario: A rejection ends the work with the person's reason
    Given the agent asked a person about the Story "story-1"
    When a person rejects the agent's review request saying "Use the photograph from the press kit instead"
    And the review request stream reaches the change feed
    And the runner takes the agent's wake for the answer
    Then the agent's run ended "nothing" with the reason "review_rejected"
    And the run's summary gives the person's reason "Use the photograph from the press kit instead"
    And the agent's procedure ran 1 time
    And the agent has 1 review request
    And the review request names that run as the one that used the answer

  Scenario: Feedback is in the next run's input and approves nothing
    Given the agent asked a person about the Story "story-1"
    When a person answers the agent's review request with the feedback "Crop the portrait to the face"
    And the review request stream reaches the change feed
    And the runner takes the agent's wake for the answer
    Then the agent's procedure was given the decision "feedback" and the words "Crop the portrait to the face"
    And the agent's run ended "asked" with the reason "human_required"
    And the agent has 2 review requests
    And the review request names that run as the one that used the answer

  Scenario: Another Story proceeds while one waits for an answer
    Given the agent asked a person about the Story "story-1"
    And on the Story "story-2" the agent's procedure needs nobody's leave
    When a person moves the Story "story-2" into "illustration"
    And the runner takes the agent's wake for the Story "story-2"
    Then the agent's run ended "acted"
    And the agent has 1 review request, open, about the run for the Story "story-1", raised by "agent:illustrate"
    And the queue holds 0 wakes
