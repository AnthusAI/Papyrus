Feature: Editors keep the publication's image style in Administration, in plain words
  Under Administration, Policies, an editor opens "Visual style" to say how the publication's pictures should look. It has a Brand page (the summary, the master
  prompt, the colours, what to prefer and avoid, and when pictures are reviewed), an Image types page (the kinds of picture the publication uses, with a page for
  each) and, for each type, the pictures that show what is wanted and what to avoid. Every change is a new version of the style with who and why, so nothing is lost
  and an older version still says what it said. The page uses flat colours and rounded shapes, Lucide icons only, and says every state in words as well as with
  an icon. These scenarios run the real page in a browser on an in-memory stand-in for the image service: no network, nothing written anywhere.

  Scenario: The Brand page shows the style and saves changes as new versions
    Given the visual style page of a publication that has a saved style
    When the editor chooses when pictures are reviewed, edits the summary and saves
    Then each change is a new version and the page says so in words
    And the selected review choice says "selected" in words, not only by its look
    And a colour without a valid hex value is refused in plain words before anything is saved
    And a change made on top of someone else's newer version is refused and the page reloads

  Scenario: Image types are listed, added with a starting type, retired and brought back
    Given the visual style page of a publication that has a saved style
    When the editor opens the Image types page
    Then each type shows its family, use, thumbnail or not, smallest size, sources in order and how many examples it has
    When the editor adds a type that starts from another one
    Then the new type extends the other and does not copy its example pictures
    And a name that is already taken, or empty, is refused in plain words
    When the editor retires the type and then brings it back
    Then it moves to Retired types and returns, and its key never changes

  Scenario: A type's page shows its rules with where each one came from
    Given the visual style page of a publication that has a saved style
    When the editor opens a type that extends another
    Then the rules in effect show the brand, the family, the parent type and this type, each line saying where it came from
    And what this type took off its parent is listed in words
    And the binding rules are shown as rules that cannot be loosened
    When the editor moves a source down and saves the guidance
    Then the sources are reordered and the guidance is saved as new versions

  Scenario: Example pictures are added, shown at their smallest size, and removed
    Given the visual style page of a publication that has a saved style
    When the editor opens a type and adds a good example and a picture to avoid
    Then a picture that is not PNG, JPEG or WebP, or is over 10 MB, is refused in plain words before it is uploaded
    And a note is required, and sending the picture to the image model is off until the editor turns it on
    And each example says whether it is good or to avoid, and whether it is sent to the image model, in words
    And a type shown as a thumbnail also shows each example at its smallest size
    When the editor removes a picture
    Then the page says older versions of the style still list it
    And a child type does not show its parent's examples

  Scenario: A publication with no style yet gets a warning in words and carries on
    Given the visual style page of a publication that has no saved style
    Then the page says the publication has no image style guidelines, so generated images will look unpredictable, and says where to fix it
    And it says pictures can still be searched for and made without a style
    When the editor drafts a starting style
    Then the draft is shown, nothing is saved, and saving it makes the first version
