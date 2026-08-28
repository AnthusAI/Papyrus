Feature: Initialize a newsroom pod story
  As a newsroom operator
  I want Kanbus to create a story with a stable identity and owned file workspace
  So that agents and editors have one durable place for the story throughout its lifecycle

  Scenario: Create a new story from an idea
    Given an initialized Anth.us newsroom pod
    When the operator creates a newsroom story through Kanbus
    Then the story begins in the configured idea stage
    And its file workspace is derived from the stable Kanbus issue identity
    And the idea artifact is available for the operator to complete
    And guidance identifies the next supported action

  Scenario: Revisit the story after another agent session
    Given a newsroom story and its file workspace already exist
    When another agent inspects the story through Kanbus
    Then the same issue identity resolves to the same file workspace
    And the current stage and next guidance are visible without reconstructing a prior chat
