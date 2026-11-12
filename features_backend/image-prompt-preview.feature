Feature: The exact request to the image model is shown before anything is made
  Before a picture is generated, an editor or an agent can ask to see exactly what would be sent to the image model, where each part of it came from and
  what it would cost. The request is compiled automatically from the publication's resolved image guidelines (the publication layer, the section layer,
  the image type and the use) through one fixed skeleton, so nobody writes style wording by hand. The preview can name a Story, can name only a section, or
  can name neither: with no Story or Reference the round is private, there is nothing to apply, and it is for ad assets and section art. An image type that
  only a section defines can be used when the section is named. A publication with no style profile gets a warning and the brief alone. The preview
  never calls an image provider, never writes a record and never spends money. A model with no price on file is shown as unpriced, never as free. Unattended
  work gets one picture; a set of several is for a person choosing. Nothing here calls a model or an image provider; the specs run against an in-memory backend.

  Scenario: The preview shows the exact request, where each part came from and an unpriced cost, and writes nothing
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a Story "story-1" in each publication
    When a person previews a "cover" prompt of type "cover-illustration" for the Story "story-1" with the brief "A locked filing cabinet"
    Then the preview succeeds with one plan
    And the plan text starts with "Flat shapes with generous rounded corners."
    And the plan text holds "Subject: A locked filing cabinet"
    And the plan says the master prompt came from the publication and the subject from the request
    And the plan carries the field sources of the resolved guidelines
    And the preview says the cost is not priced
    And the preview made no records and called no provider

  Scenario: A preview with only a section and no Story uses the section layer and is private
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And the section "security" has an image document that adds the guidance "Keep it quiet." and avoids "keys"
    When a person previews a "cover" prompt of type "cover-illustration" for the section "security" with the brief "Section art for security"
    Then the preview succeeds with one plan
    And the plan is private with nothing to apply
    And the plan text holds "Keep it quiet."
    And the plan avoids "keys"

  Scenario: A preview with neither Story nor section is a private round on the publication layer alone
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When a person previews a "cover" prompt of type "cover-illustration" with no Story and no section with the brief "An advertising tile"
    Then the preview succeeds with one plan
    And the plan is private with nothing to apply

  Scenario: An image type that only a section defines can be previewed for that section
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And the section "security" has an image document with its own image type "process-diagram"
    When a person previews a "inline" prompt of type "process-diagram" for the section "security" with the brief "How a lock is checked"
    Then the preview succeeds with one plan
    And the plan is for the image type "process-diagram"

  Scenario: A photographic image type is refused where the publication's binding rule forbids generated photographs
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When a person previews a "cover" prompt of type "cover-photo" with no Story and no section with the brief "A real street"
    Then the preview is refused with "source_not_allowed"

  Scenario: A publication with no style profile warns and continues with the brief alone
    Given an image publication "plain" with no style profile
    When a person previews a "cover" prompt with no Story and no section with the brief "An advertising tile"
    Then the preview succeeds with one plan
    And the preview warns "profile_missing"
    And the plan text is only "Subject: An advertising tile"

  Scenario: An agent asking for a set of pictures is told a set needs a person
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an agent previews a set of 4 "cover" prompts of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then the preview is refused with "set_needs_person"

  Scenario: A person asking for a set of four gets four plans and the cost is priced only when the model has a price
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When a person previews a set of 4 "cover" prompts of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then the preview succeeds with 4 plans
    And the preview says the cost is not priced

  Scenario: The preview says whether generation is configured and spending approved
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When a person previews a "cover" prompt of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then the capability check says generation is not configured and spending is not approved
