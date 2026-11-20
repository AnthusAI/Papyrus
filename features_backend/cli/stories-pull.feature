Feature: Pull a Story's stored text with papyrus stories pull
  An editing agent that owns a Story needs the text exactly as it is stored: the body and the front matter of the current version,
  with the picture paths the version stores and the citation data the live page loses. `papyrus stories pull --story LINEAGE --body-file B
  --front-matter-file F` writes those two files. `--version N` pulls that exact, immutable version instead of the current one. The two
  files are what `stories save-version --body-file --front-matter-file` takes back. `save-version` never skips a save, so saving the
  pulled files unchanged makes one new version whose text equals the one pulled. Pulling is a read: it writes two local files and
  nothing to the Story. An unknown Story or version is a clear error and no file is written.

  Background:
    Given a Story "edge-story" with a first version and a second, current version

  Scenario: Pull writes the current body and front matter to the two files
    When the agent pulls "edge-story" to a body file and a front matter file
    Then the pull succeeds and prints version 2
    And the body file holds the text of version 2 exactly
    And the front matter file holds the front matter of version 2 exactly

  Scenario: Pulling then saving the unchanged files makes one new version with the same text
    When the agent pulls "edge-story" to a body file and a front matter file
    And the agent saves the pulled files unchanged as a new version
    Then "edge-story" has 3 versions
    And version 3 has the same body and front matter as version 2
    And the picture paths of version 3 are the stored paths of version 2

  Scenario: Pulling an older version gives that version's text
    When the agent pulls version 1 of "edge-story"
    Then the body file holds the text of version 1 exactly
    And the front matter file holds the front matter of version 1 exactly

  Scenario: An unknown Story is an error and writes no file
    When the agent pulls "no-such-story" to a body file and a front matter file
    Then the pull fails saying "No story found for lineage no-such-story"
    And no file was written

  Scenario: An unknown version is an error naming the versions that exist
    When the agent pulls version 9 of "edge-story"
    Then the pull fails saying "has no version 9 (it has 2, 1)"
    And no file was written

  Scenario: Pulling writes nothing to the Story
    When the agent pulls "edge-story" to a body file and a front matter file
    Then no Story row was created or updated

  Scenario: Pull prints JSON on request
    When the agent pulls "edge-story" as JSON
    Then the JSON names story "edge-story", version 2 and both files
