Feature: A run's input, output and error are kept in S3, not in the catalog
  A run's row in the catalog holds keys and short summaries. What the run was given and what it made can be whole documents, and text does not
  belong in DynamoDB, so one run has one stored body: a single JSON file of its input, its normalized input, its output and its error. Reading a
  run's body gives back exactly what was stored. A run whose stored body is missing says so plainly, naming the run, and never shows an empty
  body in its place.

  Scenario: A run's body is stored once and read back whole
    Given a store for run bodies
    When the body of run "run-1" is stored with the input "story-1" and the output "a drafted title"
    Then reading the body of run "run-1" gives the input "story-1" and the output "a drafted title"
    And the run has exactly one stored body

  Scenario: Storing the body again replaces it
    Given a store for run bodies
    When the body of run "run-1" is stored with the input "story-1" and the output "a first title"
    And the body of run "run-1" is stored with the input "story-1" and the output "a second title"
    Then reading the body of run "run-1" gives the input "story-1" and the output "a second title"
    And the run has exactly one stored body

  Scenario: A run with no stored body says which run it is
    Given a store for run bodies
    When the body of run "run-9" is read
    Then the read fails saying that run "run-9" has no stored body
