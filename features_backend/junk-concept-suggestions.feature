@backend @junk-concept-suggestions
Feature: Suggestions to nodes that are not concepts are listed and, on request, retired
  Before concept suggestions left out authors and the graph's own bookkeeping, the vector pass offered editors "related concepts" such as a paper author,
  a coverage question or a quality rating. A tool lists the open suggestions the vector pass made to such nodes. It writes nothing unless it is told to execute;
  then it marks each one rejected, by the cleanup and with the reason "not a concept", through the same decision an editor's rejection uses. The suggestion leaves
  every queue and is not offered again, nothing is deleted, and because the calibration learns only from people's decisions these rejections teach it nothing.

  Scenario: A dry run lists the junk suggestions and writes nothing
    Given open vector suggestions to a paper author, a coverage question and the task "translation"
    When the tool runs without execute
    Then it lists the author and the coverage question
    And no suggestion was changed

  Scenario: Executing marks them rejected by the cleanup and deletes nothing
    Given open vector suggestions to a paper author, a coverage question and the task "translation"
    When the tool runs with execute
    Then the author and the coverage question suggestions are rejected by the cleanup with the reason "not_a_concept"
    And the suggestion to the task is untouched
