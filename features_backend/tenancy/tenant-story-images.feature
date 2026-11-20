Feature: Pictures saved on a tenant site can be published
  A site that serves one publication from a tenant of its backend saves its story pictures exactly where every other site
  saves them. A picture's address in the text, "assets/<slug>/<file>", is also the name its renditions are made and looked up
  under, and its stored file is always "media/assets/<slug>/<file>": the tenant is told apart by the rows it owns and by its
  own backend and site bucket, never by a folder in the file's key. So the picture a signed-in editor or agent saves with
  "papyrus stories save-version --images" is the picture the site's image function finds when the bucket announces it, and
  the picture the publish check finds when the story is published.
  A story saved before this rule, whose pictures sit under "media/<tenant>/assets/...", is repaired without uploading anything
  again: "papyrus stories repair-image-paths" copies each stored file to the one key inside the bucket and points the story's
  media rows at it. It only plans unless given --write, and it leaves the old files in place. A signed-in editor can ask for a
  picture's renditions again with "papyrus ops content renditions --source <address>" without any AWS login: the command uses
  the editor's own access to the bucket, which announces the file again to the site's image function.

  Background:
    Given a story "hello" with a first draft
    And the story belongs to the tenant "machines-on-machines"
    And a folder of pictures
    And the folder holds "chart.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    And the CLI uses the signed-in user lane
    And an identity pool is configured

  Scenario: A tenant story's picture is stored at the same key as on any other site
    When the story is saved with the folder of pictures
    Then the save succeeds
    And the only stored file is "media/assets/hello/chart.png"
    And the media row for "assets/hello/chart.png" is stored at "media/assets/hello/chart.png"

  Scenario: The media rows name the key where the file exists, never a tenant folder
    When the story is saved with the folder of pictures
    Then the media row for "assets/hello/chart.png" is stored at "media/assets/hello/chart.png" where the file exists

  Scenario: The published media row names the key where the file exists
    When the story is saved with the folder of pictures
    And the bucket announces the stored pictures to the site's image function
    Then the new version can be published
    And the published media row for "assets/hello/chart.png" is stored at "media/assets/hello/chart.png" where the file exists

  Scenario: Save, renditions and publish agree on a tenant site
    When the story is saved with the folder of pictures
    And the bucket announces the stored pictures to the site's image function
    Then the renditions exist for "assets/hello/chart.png"
    And the publish check of the new version passes
    And the new version can be published

  Scenario: Publishing before the renditions exist is refused with a command that works
    When the story is saved with the folder of pictures
    Then the publish check of the new version is refused before anything is written
    And the refusal names "assets/hello/chart.png", "media/assets/hello/chart.png" and "papyrus ops content renditions --source assets/hello/chart.png"
    And nothing is published

  Scenario: A story saved with the old tenant key is repaired without uploading again
    Given the story's picture was saved under the old tenant key
    When the repair is planned
    Then the plan copies "media/machines-on-machines/assets/hello/chart.png" to "media/assets/hello/chart.png"
    And nothing was changed by the repair
    When the repair is written
    Then the story's media rows point at "media/assets/hello/chart.png"
    And both the old and the new file are stored
    And no file was uploaded again
    When the bucket announces the stored pictures to the site's image function
    Then the publish check of the new version passes

  Scenario: A row left pointing at the tenant key while the file sits at the one key is pointed at the file
    Given the story's picture was saved at the one key but its media rows name the old tenant key
    When the repair is planned
    Then the plan copies nothing and re-points the rows to "media/assets/hello/chart.png"
    And nothing was changed by the repair
    When the repair is written
    Then the story's media rows point at "media/assets/hello/chart.png"
    And only the rows' storage paths were written
    And no file was uploaded again

  Scenario: A repair whose file is missing leaves the story as it was
    Given the story's picture was saved under the old tenant key
    And the old file is gone from the bucket
    When the repair is written
    Then the repair fails naming "media/machines-on-machines/assets/hello/chart.png"
    And the story's media rows still point at "media/machines-on-machines/assets/hello/chart.png"

  Scenario: A story that is already at the one key has nothing to repair
    When the story is saved with the folder of pictures
    And the repair is written
    Then the repair says there is nothing to repair
    And no file was uploaded again

  Scenario: A signed-in editor asks for renditions without an AWS login
    When the story is saved with the folder of pictures
    And renditions are requested for "assets/hello/chart.png" by the signed-in editor
    Then the request succeeds and the file was announced again
    When the bucket announces the stored pictures to the site's image function
    Then the publish check of the new version passes

  Scenario: Asking for renditions of a picture stored under the old tenant key says how to move it
    Given the story's picture was saved under the old tenant key
    When renditions are requested for "assets/hello/chart.png" by the signed-in editor
    Then the request fails naming "media/assets/hello/chart.png" and "papyrus stories repair-image-paths"
