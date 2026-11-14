Feature: A publication names its own image types and each request names one
  A site needs several kinds of picture, and the same family needs different rules depending on where it appears and how small it is shown. So the
  profile holds named image types: a headline illustration that must still read as a small card, a larger illustration inside the article, a technical
  diagram drawn with the figure system. A type has its own guidance, sizes, display, allowed sources in order and examples, and may extend one other
  type. Resolving the style for a request walks the layers from broadest to narrowest (identity, treatment, use, image type with its parents first,
  section, Story) and says, for every word, which layer it came from. Binding constraints and what the publication never wants are union-only: nothing
  narrower can weaken them. Type keys are permanent; a type is retired, never renamed. Style wording lives in data, and a lint keeps it out of code.

  Scenario: Precedence is previewable with the layer every field came from, including the type and its parent
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    And the section "security" says "Keep security calm." and avoids "padlocks"
    And the Story "story-1" says to avoid "keys"
    Given the request names the image type "inline-illustration"
    And the request is for the section "security"
    When the style is resolved for the "inline" use of "story-1" in "ours"
    Then the layers run publication, treatment, use, the parent image type, the image type, section and Story, in that order
    And the sizes come from the parent image type and the sources from the image type
    And the guidance lines come from the treatment, the parent type, the type and the section, in that order
    And "padlocks" and "keys" are in the things to avoid, from the section and the Story

  Scenario: A child type's removal of what its parent avoids is recorded and cannot touch a rule or a never item
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    Given the request names the image type "inline-illustration"
    When the style is resolved for the "inline" use of "story-1" in "ours"
    Then "small details" is no longer avoided and the removal is recorded against the image type
    And "real people" is still avoided
    When an editor tries to save a type that removes "real people" from its parent
    Then the save is refused as a conflict with the publication's rules
    When an editor tries to save a type that removes the binding constraint from its parent
    Then the save is refused as a conflict with the publication's rules

  Scenario: A Story or a section cannot remove a constraint or loosen what the publication forbids
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    And the Story "story-1" tries to clear the constraints and remove "real people"
    Given the request names the image type "cover-illustration"
    And the request is for generation
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the binding constraint is still in force and "real people" is still avoided
    And the answer warns that the Story's attempt was ignored

  Scenario: A section may narrow a type's sources but never add one
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    And the section "security" allows only the sources "stock" for the type "cover-illustration"
    And the request names the image type "cover-illustration"
    And the request is for the section "security"
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the effective sources are "stock" and they came from the section
    When the section "security" asks the type "cover-photo" to also allow "generated"
    And the request names the image type "cover-photo"
    And the style is resolved for the "cover" use of "story-1" in "ours"
    Then the effective sources are still "stock" and the answer warns that a source cannot be added

  Scenario: A section that asks for a treatment the publication forbids is a conflict
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    And the section "security" asks for the treatment "photo"
    Given the request names the image type "cover-illustration"
    And the request is for generation
    And the request is for the section "security"
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the answer is a conflict that names the binding constraint

  Scenario: Cycles and unknown parents are refused when the profile is saved
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an editor tries to save types that extend each other in a circle
    Then the save is refused as invalid and the message says the types extend each other in a circle
    When an editor tries to save a type that extends a type that does not exist
    Then the save is refused as invalid and the message names the missing parent
    And nothing new is stored

  Scenario: Binding constraints may only be defined at the publication level
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an editor tries to save an image type that carries its own constraints
    Then the save is refused as invalid and the message says binding rules belong to the publication

  Scenario: An image type key is permanent and a type is retired instead
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    When an editor tries to remove the type "cover-photo" from the profile
    Then the save is refused as invalid and the message says to retire it instead
    When an editor retires the type "cover-photo"
    Then the type is no longer offered for covers
    And asking for "cover-photo" is refused as an unknown or retired type with the available choices
    And resolving it for an old picture that used it still works

  Scenario: An omitted type on a cover picks the default for the use and says so
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the type is "cover-diagram", chosen as the default for the use, and the answer warns which type it picked
    When the request is for generation
    And the style is resolved for the "cover" use of "story-1" in "ours"
    Then the type is "cover-illustration", chosen as the default for the use, and the answer warns which type it picked

  Scenario: An omitted type inline is refused and the choices are listed
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    When the style is resolved for the "inline" use of "story-1" in "ours"
    Then the answer is that an image type is required, listing "inline-diagram" and "inline-illustration" with their descriptions

  Scenario: Asking for an image type the publication does not have is refused
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    Given the request names the image type "neon-poster"
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the answer is that the image type is unknown, listing the types available for covers

  Scenario: A figure-system type is never generated or searched
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    Given the request names the image type "cover-diagram"
    And the request is for generation
    When the style is resolved for the "cover" use of "story-1" in "ours"
    Then the answer is that the source is not allowed, listing "figure-system" as the type's source and where its rules live

  Scenario: Style wording in prompt code fails the lint
    Then the prompt skeleton holds no wording outside its slots, labels and joining words
    And the lint fails on a sample that puts style wording in code
    And the lint fails on a sample that puts a negative in code
