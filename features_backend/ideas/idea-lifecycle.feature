Feature: The Idea lifecycle is data that agents read
  An idea is an Item at the idea stage. It is generated, selected, assigned for research, or spiked with a reason. The stages, who moves each one, where a person is wanted
  and what happens when nobody acts are written as a file the selecting agent and the ideating agent load. At the rung propose and below the selecting agent recommends
  ideas and selects none, so a person selects; at a higher rung it selects, must be picky, compares each idea with the section's mission and recent Stories and takes at
  most what the site's policy allows. An idea nobody selects stays an idea: it is counted and never silently removed, and no idea is spiked, closed or removed for its age.
  A spiked idea records why.

  Scenario: Each stage of the Idea lifecycle names its mover
    Given the lifecycle of "Idea"
    Then its stages are "Generated, Selected, Assigned for research, Spiked"
    And every stage names a mover that is a responsibility in the catalog or the engine
    And the "Generated" stage is moved by "Ideate"
    And the "Selected" stage is moved by "Select and assign"

  Scenario: At the rung propose the agent recommends and a person selects
    Given the lifecycle of "Idea"
    Then the "Selected" stage asks a person below the rung "draft"
    And the "Selected" stage's words say "recommends ideas and selects none"

  Scenario: At a higher rung the agent selects, picky, and assigns research
    Given the lifecycle of "Idea"
    Then the "Selected" stage's words say "compares each idea with the section's mission"
    And the "Selected" stage's words say "takes at most what the site's policy allows"
    And the "Assigned for research" stage is moved by "Select and assign"
    And the "Assigned for research" stage asks no person

  Scenario: An idea nobody selects stays and is counted
    Given the lifecycle of "Idea"
    Then when nobody acts the "Selected" stage keeps the record and counts it
    And the "Selected" stage's words say "ideas are never spiked for age"
    And no stage removes a record for its age

  Scenario: A spiked idea records why
    Given the lifecycle of "Idea"
    Then the "Spiked" stage asks a person below the rung "draft"
    And the "Spiked" stage's words say "only with a reason"
    And the "Spiked" stage's words say "the reason is recorded with the idea"

  Scenario: A failed research Assignment is flagged once and waits
    Given the lifecycle of "Idea"
    Then when nobody acts the "Assigned for research" stage flags once and waits
