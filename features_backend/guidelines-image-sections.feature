Feature: A section's image guidelines are a document of their own, and the command line and the door resolve them the same way
  A publication's image guidelines say how its pictures look. A section can narrow them for its own pictures: a smaller palette, fewer sources, extra
  guidance, things to avoid. That section layer is a guideline document of the image kind at section scope, stored like the publication's: a catalog row in
  the database and the document itself in S3. The image resolver's rules do not change. A section may only narrow a choice and never add one, and it can
  never change the binding rules. A section with no image document of its own keeps using the visual style and visual guidance fields it always had, so a site
  that has not moved yet resolves as before. The signed-in command line and the door lay the same section layer over the profile. Nothing here calls a model
  or an image provider; the specs run against an in-memory backend that holds no real files.

  Scenario: A section image document narrows the site's palette
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    And the section "security" has an image document that keeps only the palette colour "Ink blue"
    And the request names the image type "cover-illustration"
    And the request is for the section "security"
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the palette of the answer is only "Ink blue"
    And the palette is credited to the section "security" at its image document version 1
    And the section's image document is stored as a catalog row and one file in S3

  Scenario: A section image document cannot add a source the site does not allow
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    And the section "security" has an image document that asks the type "cover-illustration" to allow the sources "stock" and "figure-system"
    And the request names the image type "cover-illustration"
    And the request is for the section "security"
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the sources of the answer are only "stock"
    And the answer warns that a section cannot add a choice

  Scenario: A section image document that tries to set a binding rule is refused when saved
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an admin saves a section image document for "security" that sets a constraint
    Then the save is refused because a section cannot set that

  Scenario: A section without an image document falls back to its old visual guidance field
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    And the section "news" says "News stays calm." and avoids "padlocks"
    And the request names the image type "cover-illustration"
    And the request is for the section "news"
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the guidance of the answer holds "News stays calm." and the avoid list holds "padlocks"
    And no file was read for the section

  Scenario: The command line and the door resolve a section's image guidance the same way
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    And the section "security" has an image document that keeps only the palette colour "Ink blue"
    And the section "security" has an image document that adds the guidance "Keep it quiet." and avoids "keys"
    When the command line and the door each resolve the "cover" use of "story-1" for the section "security" and the type "cover-illustration"
    Then both answers give the same effective guidance, sources and layers
    And both answers hold the guidance "Keep it quiet." and the palette "Ink blue" only
