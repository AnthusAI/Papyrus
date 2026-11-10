Feature: A section's writing guidelines are laid over the site's, field by field
  A section can add to the publication's writing guidelines and can choose for itself only what the publication leaves open. Prose is added, never
  replaced: the section's tone and voice patterns come after the publication's. Lists of words to avoid are joined, so a section can never remove a
  word the publication avoids. Choices such as the audience are the section's unless the publication locks them. Binding constraints belong to the
  publication alone, and a section that sets them is ignored with a warning. Every answer names, for every field, the layer it came from and the
  version of that layer, so a draft can be traced to the exact guidelines it used. A publication with no writing guidelines still resolves, with a
  warning and nothing applied; nothing is refused. This step builds the resolver; it calls no model and touches no live account.

  Background:
    Given a publication whose writing guidelines have the tone "Warm.", avoid the word "synergy", have the audience open and lock the headline

  Scenario: A section adds tone and voice patterns after the site's
    Given the section "news" has writing guidelines with the tone "Brisk." and the voice pattern "Short leads."
    When the writing guidelines are resolved for the section "news"
    Then the tone reads "Warm." then "Brisk."
    And the voice patterns end with "Short leads."

  Scenario: A section cannot remove a word the site avoids
    Given the section "news" has writing guidelines that avoid "leverage" and prefer nothing
    When the writing guidelines are resolved for the section "news"
    Then the words to avoid are "synergy" then "leverage"

  Scenario: A section replaces the audience when the site leaves it open
    Given the section "news" has writing guidelines with the audience "Engineers"
    When the writing guidelines are resolved for the section "news"
    Then the audience is "Engineers"
    And there are no warnings

  Scenario: A section cannot replace a field the site locks
    Given the section "news" has writing guidelines with a different headline order
    When the writing guidelines are resolved for the section "news"
    Then the headline order is the site's
    And the warning "locked_field_ignored" names the field "headline"

  Scenario: A section's binding constraint is ignored with a warning
    Given the section "news" has writing guidelines with a binding constraint
    When the writing guidelines are resolved for the section "news"
    Then the constraints are the site's alone
    And the warning "section_constraint_ignored" is given

  Scenario: A site with no writing guidelines resolves with a warning, not an error
    Given a publication with no guidelines
    When the writing guidelines are resolved for the section "news"
    Then nothing was found and the document is empty
    And the warning "writing_guidelines_missing" is given

  Scenario: A section with no guidelines of its own gets the site's
    When the writing guidelines are resolved for the section "sports"
    Then the tone reads "Warm."
    And one layer was used, the publication's

  Scenario: Every resolved field names the layer and version it came from
    Given the section "news" has writing guidelines with the tone "Brisk." and the audience "Engineers"
    When the writing guidelines are resolved for the section "news"
    Then the source of "tone" is the publication at version 1 and the section at version 1
    And the source of "audience" is the section at version 1
    And the source of "voice" is the publication at version 1
    And every field of the answer has a source
    And the layers list the slugs "editorial-doctrine-writing" and "desk-doctrine-news-writing" with their content hashes
