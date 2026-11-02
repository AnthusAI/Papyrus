Feature: Saving a story version with the pictures its text uses
  An agent or editor writes a story as a text file next to the picture files it uses. "papyrus stories save-version
  --images <folder>" uploads every picture the text points at, exactly as the newsroom editor's "Insert image" would:
  one media row per picture on the new version, and one stored file per picture under assets/<story slug>/. The text
  is then saved with each picture's address rewritten to the stored one. Both ::image{src="..."} lines and Markdown
  ![...](...) pictures count when the address is a relative path found inside the folder; web addresses and pictures
  the folder does not hold are left alone. A picture named like another with ".dark" before the extension
  (figure.png and figure.dark.png), or one named by srcDark, is the dark-mode version: it is uploaded too and the
  ::image line gets an explicit srcDark. Every file is checked before anything is written: at most 10 MB, a PNG, JPEG,
  GIF, WebP, AVIF or SVG picture, and a dark version with the same proportions as its light version (within 0.5%).
  A rejection names the file and nothing is saved. "--dry-run" prints what would be uploaded (file, media id, stored
  path, size and dark pairing) and writes nothing at all. Running the same command again does not add media rows or
  stored files twice: a picture already stored for the story keeps its exact path, even if the story's address has since
  changed, and a name holding different content is numbered (-2), never overwritten. Pictures never move when the story
  is published or given a real address; a story with only a generated draft address uses it, as the editor does. The command works for both kinds of sign-in: an operator using AWS credentials, and a signed-in
  editor or admin, whose upload uses temporary credentials from the site's identity pool instead.

  Background:
    Given a story "hello" with a first draft
    And a folder of pictures

  Scenario: A picture and its dark version are uploaded and the text points at the stored paths
    Given the folder holds "chart.png" at 800 by 400 pixels and "chart.dark.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    Then the save succeeds
    And the saved text points at "assets/hello/chart.png" with srcDark "assets/hello/chart.dark.png"
    And the new version has media rows for "assets/hello/chart.png" and "assets/hello/chart.dark.png"
    And the media row for "assets/hello/chart.png" is a body image stored at "media/assets/hello/chart.png" named "chart.png"
    And the stored files are "media/assets/hello/chart.png" and "media/assets/hello/chart.dark.png"
    And the new version can be published

  Scenario: A Markdown picture is uploaded too, and a web picture is left alone
    Given the folder holds "photo.png" at 300 by 200 pixels
    And the new text has a Markdown picture "photo.png" and a Markdown picture "https://example.com/web.png"
    When the story is saved with the folder of pictures
    Then the saved text has the Markdown picture "assets/hello/photo.png" and the Markdown picture "https://example.com/web.png"
    And the new version has media rows for "assets/hello/photo.png"

  Scenario: A dry run prints the plan and writes nothing
    Given the folder holds "chart.png" at 800 by 400 pixels and "chart.dark.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures as a dry run
    Then the plan lists "chart.png" with its media id, "media/assets/hello/chart.png" and its size in bytes
    And the plan lists "chart.dark.png" as the dark version of "chart.png"
    And nothing was written to the backend or to storage

  Scenario: A picture over 10 MB is rejected by name
    Given the folder holds "huge.png" larger than 10 MB
    And the new text is an image line for "huge.png"
    When the story is saved with the folder of pictures
    Then the save is rejected naming "huge.png" and "10 MB"
    And nothing was written to the backend or to storage

  Scenario: A file that is not a supported picture type is rejected by name
    Given the folder holds a file "notes.txt" with some text
    And the new text is an image line for "notes.txt"
    When the story is saved with the folder of pictures
    Then the save is rejected naming "notes.txt" and "PNG, JPEG, GIF, WebP, AVIF or SVG"
    And nothing was written to the backend or to storage

  Scenario: A dark version with different proportions is rejected by name
    Given the folder holds "chart.png" at 800 by 400 pixels and "chart.dark.png" at 800 by 500 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    Then the save is rejected naming "chart.dark.png" and "aspect ratio"
    And nothing was written to the backend or to storage

  Scenario: A dark version off by a pixel of rounding is accepted
    Given the folder holds "chart.png" at 1000 by 500 pixels and "chart.dark.png" at 1000 by 501 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    Then the save succeeds

  Scenario: An explicit srcDark file with any name is uploaded as the dark version
    Given the folder holds "chart.png" at 800 by 400 pixels and "night.png" at 800 by 400 pixels
    And the new text is an image line with src "chart.png" and srcDark "night.png"
    When the story is saved with the folder of pictures
    Then the saved text points at "assets/hello/chart.png" with srcDark "assets/hello/night.png"

  Scenario: Running the same save again does not duplicate media rows or stored files
    Given the folder holds "chart.png" at 800 by 400 pixels and "chart.dark.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    And the story is saved again with the same text and the same folder
    Then the second save succeeds
    And the second save found the stored files already in place
    And each version has exactly one media row for each of "assets/hello/chart.png" and "assets/hello/chart.dark.png"
    And the media ids are the same ones the editor and the Markus import derive from the version and the stored path
    And the stored files are still just "media/assets/hello/chart.png" and "media/assets/hello/chart.dark.png"

  Scenario: A story with only a generated draft address stores its pictures under that address, as the editor does
    Given the story's address becomes "draft-unsectioned-1a2b3c4d"
    And the folder holds "chart.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    Then the saved text points at "assets/draft-unsectioned-1a2b3c4d/chart.png" with no srcDark
    And the stored files are "media/assets/draft-unsectioned-1a2b3c4d/chart.png" and "media/assets/draft-unsectioned-1a2b3c4d/chart.png"

  Scenario: Giving the story a real address later does not move its pictures, and a re-run keeps the stored path
    Given the story's address becomes "draft-unsectioned-1a2b3c4d"
    And the folder holds "chart.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    And the story's address becomes "a-real-title"
    And the story is saved again with the same text and the same folder
    Then the second save succeeds
    And the saved text points at "assets/draft-unsectioned-1a2b3c4d/chart.png" with no srcDark
    And the second save found the stored files already in place
    And the stored files are "media/assets/draft-unsectioned-1a2b3c4d/chart.png" and "media/assets/draft-unsectioned-1a2b3c4d/chart.png"

  Scenario: A different picture under a name already used is numbered, never overwritten
    Given the folder holds "chart.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    And the picture "chart.png" is replaced by a different one at 600 by 300 pixels
    And the story is saved again with the same text and the same folder
    Then the saved text points at "assets/hello/chart-2.png" with no srcDark
    And the stored files are "media/assets/hello/chart.png" and "media/assets/hello/chart-2.png"

  Scenario: An operator using AWS credentials uploads with them
    Given the CLI uses the IAM lane
    And the folder holds "chart.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    Then the save succeeds
    And the upload used the operator's AWS credentials
    And no identity-pool credentials were requested

  Scenario: A signed-in editor uploads with temporary identity-pool credentials
    Given the CLI uses the signed-in user lane
    And the folder holds "chart.png" at 800 by 400 pixels and "chart.dark.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    Then the save succeeds
    And the identity pool was given the signed-in user's ID token
    And the stored files were uploaded with the temporary credentials the pool returned
    And the media rows were written through the signed-in session's GraphQL client
    And no AWS credentials of the operator were used

  Scenario: A signed-in user without an identity pool is told what to configure and nothing is saved
    Given the CLI uses the signed-in user lane
    And no identity pool is configured
    And the folder holds "chart.png" at 800 by 400 pixels
    And the new text is an image line for "chart.png"
    When the story is saved with the folder of pictures
    Then the save is rejected naming "identity pool"
    And the story still has only its first version
