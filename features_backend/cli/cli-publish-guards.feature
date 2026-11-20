Feature: The CLI publish commands say honestly whether a page went live
  An operator publishes a story from the command line. Publishing has two halves: the published records in the data,
  and the page that the projection writes to the site. The command must never report success when only the first half
  happened, must not let a story go live at a throwaway address, and must not let a board move pass for a publish.

  Scenario: A signed-in publish triggers the projection through the newsroom's own publish mutation
    Given a site that projects its pages
    And a saved draft story with the slug "my-story"
    And the CLI is signed in as a newsroom user with no AWS credentials
    When the operator publishes the story
    Then the published records are written
    And the projection was requested through the "publishItem" mutation for the story
    And no AWS function was invoked
    And the command exits successfully

  Scenario: A signed-in unpublish triggers the projection through the unpublish mutation
    Given a site that projects its pages
    And a saved draft story with the slug "my-story"
    And the story is published
    And the CLI is signed in as a newsroom user with no AWS credentials
    When the operator unpublishes the story
    Then the projection was requested through the "unpublishItem" mutation for the story
    And the command exits successfully

  Scenario: A failed projection makes the publish exit with an error that says what is and is not live
    Given a site that projects its pages
    And a saved draft story with the slug "my-story"
    And the projection trigger fails
    When the operator publishes the story
    Then the published records are written
    And the command exits with an error
    And the output says the data is published but the page is not
    And the output names the command "papyrus ops content publish --id" to retry

  Scenario: A projection refused by the newsroom is reported the same way
    Given a site that projects its pages
    And a saved draft story with the slug "my-story"
    And the CLI is signed in as a newsroom user with no AWS credentials
    And the newsroom's publish mutation reports that the projection failed
    When the operator publishes the story
    Then the command exits with an error
    And the output says the data is published but the page is not

  Scenario: A machine-readable publish carries the same facts
    Given a site that projects its pages
    And a saved draft story with the slug "my-story"
    And the projection trigger fails
    When the operator publishes the story asking for JSON
    Then the command exits with an error
    And the JSON reports the data as published and the page as not published, with a retry command

  Scenario: Skipping the trigger on purpose is still a success
    Given a site that projects its pages
    And a saved draft story with the slug "my-story"
    When the operator publishes the story without triggers
    Then the command exits successfully

  Scenario: A story with a placeholder slug cannot be published
    Given a site that projects its pages
    And a saved draft story with the slug "draft-unsectioned-1a2b3c4d5e6f7a8b"
    When the operator publishes the story
    Then the command exits with an error
    And the output names "stories set-slug"
    And the publish wrote nothing
    And no projection was requested for the story

  Scenario: A dry run refuses a placeholder slug too
    Given a site that projects its pages
    And a saved draft story with the slug "draft-unsectioned-1a2b3c4d5e6f7a8b"
    When the operator previews publishing the story
    Then the command exits with an error
    And the output names "stories set-slug"

  Scenario: Moving a story to the published stage warns that no page is published
    Given a story on the board
    When the operator moves the story to the "published" stage
    Then the warning says no page is published and names "papyrus ops content publish"
    And the story's stage is "published"

  Scenario: The warning also appears in a dry run, which writes nothing
    Given a story on the board
    When the operator previews moving the story to the "published" stage
    Then the warning says no page is published and names "papyrus ops content publish"
    And the story's stage is unchanged

  Scenario: Moving a story to another stage prints no such warning
    Given a story on the board
    When the operator moves the story to the "reporting" stage
    Then no publish warning is printed
