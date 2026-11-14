Feature: A reviewer sees a Story's headline image on the Story detail
  The Story detail, both the drawer opened from the board and the full article page, shows the Story's headline image at the top, above the fields
  and the preview, so a reviewer judges the picture together with the text. The headline image is the one a card and a share use: the first of the
  front matter keys image, cover, ogImage and thumbnail that has a value. It is read-only here; the cover picker and the media upload still change
  it. It is drawn on a flat rounded surface with no outline, and its alt text is written under it. The view always says something: when there is no
  picture, when the picture is still loading or processing, and when the file is missing or cannot be read, it says so in words and never leaves a
  blank. A draft version shows its own picture, because the view reads the front matter of the version that is open, including unsaved edits.

  Scenario: A Story with a headline image shows it with its alt text
    Given a Story whose front matter names a site-media image
    When the Story detail opens
    Then the picture is shown above the editor and the preview
    And its alt text is the figure's alt, else the cover's title, else the Story's title

  Scenario: The first headline key with a value is the one shown
    Given a Story that sets thumbnail and ogImage but not image or cover
    When the headline image is read
    Then ogImage is the one shown

  Scenario: A stored path with a leading slash finds its media file
    Given a cover set by the cover picker, stored as a path with a leading slash
    When the media files are listed
    Then the picture is found by the same name the media row carries

  Scenario: No headline image says so
    Given a Story whose front matter sets none of the headline keys
    When the Story detail opens
    Then it says there is no headline image and that cards and shares have no picture

  Scenario: A picture still being prepared says so
    Given a media row for the picture that has no stored file yet
    When the Story detail opens
    Then it says the headline image is still processing

  Scenario: A missing or unreadable picture says why
    Given a Story naming a file with no media row, a file the storage cannot read, or a media list that fails
    When the Story detail opens
    Then it says which of the three happened, in words

  Scenario: A draft version shows its own picture
    Given a draft whose image differs from the published version's
    When the draft is open
    Then the draft's picture is shown
