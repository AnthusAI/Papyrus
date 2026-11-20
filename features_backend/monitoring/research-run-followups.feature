@backend @research-run-followups
Feature: A research run that cannot write to disk, or whose sources were not taken in, can be repaired and says so
  The first real run of a research.multi assignment by the worker in the cloud took in none of its sources, because the step that takes a packet's
  sources into the newsroom writes a catalog file under the code directory, and in the cloud that directory cannot be written. Now that step writes
  under the directory the environment names in PAPYRUS_RUNS_DIR (a Lambda names one under /tmp), and stops with an error that names the setting when neither it
  nor the code directory can be written. The operator command that takes the sources in by hand,
  process-proposals with cited-only, also finishes the job a research run does: it links the taken-in and the already held References to the Story as
  consulted by the assignment, and summarizes the taken-in ones. It can be run twice: it adds no second link, lowers no role and keeps what is written.

  Scenario: The step that takes sources in writes under PAPYRUS_RUNS_DIR when the code directory is read-only
    Given a code directory that cannot be written and PAPYRUS_RUNS_DIR naming a writable directory
    When the sources of a research packet are taken in
    Then the catalog was written under the configured run directory

  Scenario: Taking sources in links the taken-in and held References and summarizes only the taken-in one
    Given a Story whose reporter research assignment found one new Reference and one already held
    When the sources are taken in by the operator command with cited-only
    Then both References are linked to the Story as consulted
    And only the new Reference was summarized

  Scenario: Taking the sources in twice adds no link, keeps a citation and keeps its note
    Given a Story whose reporter research assignment found one new Reference and one already held
    And the Story already cites the new Reference with the note "kept note"
    When the sources are taken in by the operator command with cited-only
    And the sources are taken in by the operator command with cited-only
    Then the Story has 2 References
    And the new Reference is still cited with the note "kept note"

  Scenario: An assignment that is not a reporter research assignment is left alone
    Given a Story whose research assignment has no reporter profile
    When the sources are taken in by the operator command with cited-only
    Then the Story has 0 References

  Scenario: Taking in a packet leaves an existing corpus record as it was
    The corpus record describes the whole publication. A research packet's intake once overwrote its count and creation date with those of one small batch.
    Given a publication whose corpus record says it was created long ago and holds many items
    When a research packet's cited sources are taken in
    Then the corpus record is unchanged
    And the cited sources are registered

