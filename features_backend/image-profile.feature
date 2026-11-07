Feature: A publication's visual style profile lives in the backend as versioned data
  A publication says how its pictures should look once, in one place that editors can read and change: a visual style profile saved as a third kind
  of doctrine next to the mission and the policy. It holds the publication's identity (summary, master prompt, palette), the things it never wants
  to see, its binding rules, its image types and a setting for when a person reviews pictures. Every edit makes a new version with who, when and why,
  and the older versions stay, so a picture can always be traced to the exact style it was made with. The style is data, never code: the only thing
  the toolchain hard-codes is the order of the slots in a prompt. A publication with no profile gets a warning and keeps working. This step builds
  the profile, its operations on the signed-in lane and the text agents read; it calls no model and no image provider and writes nothing outside a fake.

  Scenario: Two publications never see each other's profile
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And an image publication "theirs" with a saved style profile whose master prompt says "Loud neon posters."
    And a Story "story-1" in each publication
    And the request names the image type "inline-illustration"
    When the style is resolved for the "inline" use of "story-1" in "ours"
    And the style is resolved for the "inline" use of "story-1" in "theirs"
    Then the answer from "ours" names the publication "ours" and its plan holds "Flat shapes" and never "neon"
    And the answer from "theirs" names the publication "theirs" and its plan holds "neon" and never "Flat shapes"
    And asking "ours" for a Story that only exists elsewhere is answered with not found

  Scenario: Records from another account are refused
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And the profile record belongs to a different account than the one signed in
    When the profile is read
    Then reading it fails because the record is outside the signed-in account

  Scenario: The first save and every later edit make a new version and old versions stay
    Given an image publication "ours" with no style profile
    When an editor saves the first style document with the reason "First profile"
    And an editor changes the summary to "Calmer." with the reason "Tuned the summary"
    Then the profile is at version 2 and says "Calmer."
    And version 1 can still be read and says "Flat and calm."
    And the history lists version 2 with the reason "Tuned the summary" before version 1 with the reason "First profile"
    And both versions are stored as separate records, the older one marked superseded

  Scenario: A save made on top of an out-of-date version is refused
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an editor saves a change naming a version that is no longer current
    Then the save is refused as stale and nothing new is stored

  Scenario: Saving a document that changes nothing makes no new version
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an editor saves the same mood the profile already has
    Then the answer says it is unchanged and the profile stays at version 1

  Scenario: Agents cannot edit the binding constraints
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an agent tries to remove the binding constraint
    Then the save is refused because a person is required and nothing new is stored
    When an editor who is not an admin tries to remove the binding constraint
    Then the save is refused as not authorised and nothing new is stored
    When an admin removes the binding constraint
    Then the profile is at version 2 with no constraints
    And version 1 still holds the constraint

  Scenario: An agent may still edit everything that is not a binding constraint
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an agent adds a mood word with the reason "Tuned the mood"
    Then the profile is at version 2 and the history says the agent made it

  Scenario: A new binding constraint is stamped with who adopted it, when and why
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an admin adds the binding constraint "no-logos" with the reason "No logos anywhere"
    Then the constraint "no-logos" is at version 1 with the admin as adopter and the reason "No logos anywhere"
    And the existing constraint is stored exactly as before

  Scenario: Previewing a change shows the differences without saving
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an editor previews dropping the binding constraint and changing the mood
    Then the preview lists the mood change and the constraint as removed and says the next version would be 2
    And nothing new is stored

  Scenario: A publication with no profile gets a warning and a plan that is only the skeleton and the brief
    Given an image publication "ours" with no style profile
    And a Story "story-1" in each publication
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the answer succeeds with the profile missing warning in the design's words
    And the plan for the brief "A locked filing cabinet" is exactly "Subject: A locked filing cabinet"
    And no constraint, style or negative appears in it

  Scenario: The review setting defaults to before publication and is saved as data
    Given an image publication "ours" with no style profile
    When an editor saves the first style document with the reason "First profile"
    Then the profile says pictures are reviewed before publication
    When an editor changes the review setting to after the fact with the reason "Review later"
    Then the profile says pictures are reviewed after the fact

  Scenario: The editorial context carries the style, and its hash changes when the style does
    Given editorial records whose publication has a saved image style
    When the editorial context is resolved including the image style
    Then it has a visual-style entry from the publication with the version and a content hash
    And its text lists the image types
    When the image style is edited and the editorial context is resolved again
    Then the context hash is different
    And an editorial context resolved without asking for the style has no visual-style entry

  Scenario: The illustrator's context pack lists each image type in one plain line and says to choose a type
    Given a newsroom whose publication has a saved image style
    When the illustrator agent's context pack is built for the Story
    Then the visual style layer lists one line for each image type grouped by use
    And a line says where the pictures of that type may come from and whether it is read as a thumbnail
    And the layer tells the agent to choose an image type before asking for a picture
    And the layer holds the rule that cannot be loosened in full

  Scenario: The editor's pack only lists the types and the reporter's pack has no style layer
    Given a newsroom whose publication has a saved image style
    When the editor agent's context pack is built for the Story
    Then the visual style layer lists the image types but not the rules or the summary
    When the reporter agent's context pack is built for the Story
    Then the pack has no visual style layer

  Scenario: The illustrator's pack warns when the publication has no style
    Given a newsroom whose publication has no saved image style
    When the illustrator agent's context pack is built for the Story
    Then the visual style layer is empty because the publication has no image style guidelines
    And the pack warns that the style of generated images will be undefined and unpredictable
