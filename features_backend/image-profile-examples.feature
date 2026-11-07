Feature: Editors keep example and avoid-this pictures on each image type of the style profile
  A publication's style is easier to show than to describe, so an editor can upload pictures to the profile and say, for one image type at a time, "this is
  the calm we want" or "avoid this". A picture is uploaded once, as a private file in the newsroom's own storage (PNG, JPEG or WebP, at most 10 MB), and then
  listed under an image type in a new profile version. The file is never copied or changed, so an older profile version still lists exactly the pictures it
  had and a picture made from it can always be traced. Examples belong to one image type: a child type does not inherit its parent's. A picture is never
  sent to an image provider unless a person allows it, because the service cannot tell whether it shows identifiable people or logos. An editor can also ask
  for a starting profile to be drafted for them; the draft is only shown and is never saved by itself. This step calls no image provider and writes nothing
  outside a fake backend.

  Scenario: An editor adds a good example to one image type
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    When an editor adds the picture "aa01" as a good example of "cover-illustration" with the note "The calm we want."
    Then the profile is at version 2
    And the type "cover-illustration" lists the picture "aa01" as an example noting "The calm we want." and not sent to a provider
    And the example records who added it and that a person did
    And the uploaded file was not touched

  Scenario: The same picture can be listed by two image types as one uploaded file
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    When an editor adds the picture "aa01" as a good example of "cover-illustration" with the note "The calm we want."
    And an editor adds the picture "aa01" as a good example of "social-card" with the note "Also right for the card."
    Then the type "cover-illustration" lists the picture "aa01" as an example noting "The calm we want." and not sent to a provider
    And the type "social-card" lists the picture "aa01" as an example noting "Also right for the card." and not sent to a provider
    And there is still one uploaded file

  Scenario: A brand-wide example belongs to the identity, not to a type
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    When an editor adds the picture "aa01" as a good example of "identity" with the note "The whole brand in one picture."
    Then the brand lists the picture "aa01" as an example

  Scenario: A child type does not inherit its parent's examples
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    When an editor adds the picture "aa01" as a good example of "cover-illustration" with the note "A thumbnail cover."
    Then the type "inline-illustration", which extends "cover-illustration", lists no examples
    And no example of "inline-illustration" can be sent to a provider

  Scenario: Pictures that cannot be examples are refused and nothing is saved
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    And a completed upload of a text file "bb02" that is not a picture
    And a completed upload of a PNG picture "cc03" larger than 10 MB
    And a completed upload of a PNG picture "dd04" meant as an avoid-this picture
    When an editor adds the picture "bb02" as a good example of "cover-illustration" with the note "Not a picture."
    Then the add is refused as invalid because examples must be PNG, JPEG or WebP
    When an editor adds the picture "cc03" as a good example of "cover-illustration" with the note "Too big."
    Then the add is refused as invalid because examples must be 10 MB or smaller
    When an editor adds the picture "dd04" as a good example of "cover-illustration" with the note "Wrong kind."
    Then the add is refused as invalid because the upload was for a different kind of picture
    When an editor adds the picture "aa01" as a good example of "neon-poster" with the note "No such type."
    Then the add is refused as an unknown image type, listing the types available
    When an editor adds a picture that was never uploaded as a good example of "cover-illustration" with the note "Missing."
    Then the add is refused as not found
    And the profile is still at version 1

  Scenario: A retired image type takes no new examples
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    When an editor retires the type "cover-photo"
    And an editor adds the picture "aa01" as a good example of "cover-photo" with the note "Too late."
    Then the add is refused as an unknown image type, listing the types available

  Scenario: Removing an example keeps the picture in the older versions
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    When an editor adds the picture "aa01" as a good example of "cover-illustration" with the note "The calm we want."
    And an editor removes the picture "aa01" from the examples with the reason "Too photographic."
    Then the profile is at version 3
    And the type "cover-illustration" lists no examples
    And version 2 of the profile still lists the picture "aa01" under "cover-illustration"
    And the uploaded file was not touched
    And removing it again is refused as not found

  Scenario: A picture made from an older version keeps the examples it was made with
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    When an editor adds the picture "aa01" as a good example of "cover-illustration" with the note "The calm we want."
    And an editor removes the picture "aa01" from the examples with the reason "Too photographic."
    Then reading version 2 of the profile gives the same example list it had when it was saved

  Scenario: An add made on top of an out-of-date version is refused
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    When an editor adds the picture "aa01" naming a version that is no longer current
    Then the add is refused as stale and the other editor's version stays current

  Scenario: Only a person may let a picture go to an image provider
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    And a completed upload of a PNG picture "ee05"
    When an agent adds the picture "aa01" as a good example of "cover-illustration" allowing it to go to a provider
    Then the add is refused because a person is required and the profile is still at version 1
    When an agent adds the picture "aa01" as a good example of "cover-illustration" with the note "The calm we want."
    Then the example is saved as added by an agent and not sent to a provider
    When an editor adds the picture "ee05" as a good example of "cover-illustration" allowing it to go to a provider
    Then the provider may be sent only the picture "ee05" for "cover-illustration"

  Scenario: An agent cannot switch a provider flag on by saving a whole document
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a completed upload of a PNG picture "aa01"
    When an editor adds the picture "aa01" as a good example of "cover-illustration" with the note "The calm we want."
    And an agent saves the same example with the provider flag switched on
    Then the add is refused because a person is required and the profile is still at version 2

  Scenario: A starting profile is drafted for an editor and never saved by itself
    Given an image publication "ours" with no style profile
    When an editor asks for a starting profile with the brand colour "Ink blue" "#1f2a44"
    Then the draft is a valid profile document holding that colour and three image types
    And the draft holds no style wording and the notes say what the editor still has to write
    And nothing was stored and the publication still has no profile
    When an editor saves the draft with the reason "First profile, from the draft"
    Then the profile is at version 1

  Scenario: Asking for a draft when a profile exists warns and changes nothing
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an editor asks for a starting profile with the brand colour "Ink blue" "#1f2a44"
    Then the answer warns that the publication already has a profile
    And the profile is still at version 1
