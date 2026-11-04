Feature: The story commands print what happened, in order, and name the right person
  An operator or an agent reads a story command's output to learn what it did. A command that creates a Story prints the Story's lineage
  id on its own labelled line, because every other command takes that id as the story to work on. A command prints its write line only
  after the write was saved, so a refused or failed write never claims success. A dry run prints its dry run line and writes nothing.
  Signed in, a reference link records the person who signed in as who added it, and a label typed on the command line cannot name someone
  else. With an operator's AWS credentials there is no sign-in, so the label is required and recorded as given. The story overview lists
  the Messages people saved on the Story, as well as the agent notes.

  Background:
    Given a Story with one saved version and one Reference for the story edge checks

  Scenario: Creating a Story prints its lineage id on its own line
    When the story edge checks create a Story titled "A new story"
    Then the output keeps its "created" line with the version record id
    And the output has a "lineage" line with the Story's lineage id
    And the version record id is the lineage id followed by "-v1"

  Scenario: A Story that could not be created prints no write line
    When the story edge checks create a Story and the save fails
    Then the story edge command prints no write line
    And the story edge command fails

  Scenario: A move that could not be saved prints no write line
    When the story edge checks move the Story to "reporting" and the save fails
    Then the story edge command prints no write line
    And the story edge command fails

  Scenario: A new version that could not be saved prints no write line
    When the story edge checks save a new version and the save fails
    Then the story edge command prints no write line
    And the story edge command fails

  Scenario: A move that was saved prints its write line first
    When the story edge checks move the Story to "reporting"
    Then the first output line is the move's write line

  Scenario: A dry run move prints its dry run line and writes nothing
    When the story edge checks move the Story to "published" as a dry run
    Then the output is only the move's dry run line
    And the warning that publishing is a separate step is printed on stderr
    And no record is written for the story edge checks

  Scenario: A reference link that could not be saved prints no write line
    When the story edge checks link the Reference with the label "ops" and the save fails
    Then the story edge command prints no write line
    And the story edge command fails

  Scenario: A signed-in person links a reference without a label
    When a signed-in person "Ada Example" links the Reference with no label
    Then the link records "Ada Example" as who added it
    And the story edge command printed its write line after the link was saved

  Scenario: A signed-in person cannot name someone else on a link
    When a signed-in person "Ada Example" links the Reference with the label "Someone Else"
    Then the link records "Ada Example" as who added it
    And the command warns on stderr that the label is ignored

  Scenario: A session that names no one cannot save a link
    When a signed-in session that names no one links the Reference
    Then the story edge command fails
    And the story edge command prints no write line
    And no relation is written for the story edge checks

  Scenario: An operator on the IAM lane must give a label and it is recorded as given
    When an operator on the IAM lane links the Reference with no label
    Then the story edge command fails
    When an operator on the IAM lane links the Reference with the label "ChatGPT"
    Then the link records "ChatGPT" as who added it

  Scenario: The story overview lists a person's saved note
    Given a person's note "Check the second source" was saved on the Story
    When the story edge checks show the Story
    Then the overview has a "message" line by "Ada Example (note)" with the summary "Check the second source"

  Scenario: The story overview lists Messages oldest first and leaves out deleted ones
    Given a person's note "First" was saved on the Story
    And a person's note "Second" was saved on the Story
    And a deleted note was saved on the Story
    When the story edge checks show the Story
    Then the overview lists the "message" summaries "First", "Second" in that order
