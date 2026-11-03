@create-story
Feature: An editor creates a Story from a Reference in one tap
  The Reference card and the Reference detail have a Create Story action. One tap makes a draft Story linked to the Reference and opens it in the article
  editor, ready to write. Create Story is one action: it makes a Story of the site's default type, and the type is a field the editor sets in the
  Story, so the card has no companion button for any one type. Making a Story from a Reference the editor has not
  decided also records the editor's own Accept, as the Accept button does, with no reason asked, and the button says so. A rejected Reference is not
  overturned, and its button says that its vote stays. A Reference that already has a Story is not given a second one silently: a second tap offers the
  existing Story, and "Create another" is a deliberate choice. In the editor, a plain note says the draft is a starting draft from the Reference's summary
  and that the picture comes from another site and needs a rights check before publishing.

  Scenario: One tap on a pending Reference makes the Story, accepts the Reference and opens the Story
    Given a References page with a pending, a rejected and an accepted Reference
    When the editor taps Create Story on the pending card
    Then the Story opens in the article editor and the Reference is accepted with no reason

  Scenario: An automatic acceptance is confirmed as the editor's own vote
    Given a References page with a pending, a rejected and an accepted Reference
    When the editor taps Create Story on the automatically accepted card
    Then the card says it confirms the automatic acceptance and the editor's Accept is recorded with no reason

  Scenario: A rejected Reference says its vote stays and is not overturned
    Given a References page with a pending, a rejected and an accepted Reference
    When the editor taps Create Story on the rejected card
    Then the card says its vote stays and no vote is recorded

  Scenario: An accepted Reference makes a Story without a second vote
    Given a References page with a pending, a rejected and an accepted Reference
    When the editor taps Create Story on the accepted card
    Then the Story opens and no vote is recorded

  Scenario: Tapping again offers the existing Story and Create another is deliberate
    Given a References page with a pending, a rejected and an accepted Reference
    When the editor taps Create Story twice on the same card and then taps Create another
    Then the second tap offers the existing Story and only the deliberate choice makes a second one

  Scenario: Create Story is one action with no button for a post
    Given a References page with a pending, a rejected and an accepted Reference
    When the editor looks at a card
    Then there is one Create Story button, no button for a post, no dialog and only Lucide icons

  Scenario: The detail pane has the same action
    Given a References page with a pending, a rejected and an accepted Reference
    When the editor opens a pending Reference and taps Create Story in the detail pane
    Then the Story opens and the Reference is accepted with no reason

  Scenario: On a phone the action is a large target
    Given a References page with a pending, a rejected and an accepted Reference
    When the editor opens the page on a phone
    Then Create Story is at least forty pixels tall and nothing scrolls sideways
