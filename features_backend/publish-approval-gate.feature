Feature: A site can require a person's approval before anything publishes
  Each site stores a publish approval setting as site data. The default is not required, so existing sites keep working.
  When it is required, a publish that no person made raises one hard gate review request about that version of the item
  and does not publish; a person approving the request lets the next publish through. An editor who presses Publish in the
  console is already a person approving, so the gate never blocks them.

  Scenario: A site that never set the gate publishes as before
    Given a saved draft article on a site with no publish gate setting
    When an automation publishes the item
    Then the item is published
    And no review request exists

  Scenario: A site that requires approval does not publish for an automation
    Given a saved draft article on a site that requires approval to publish
    When an automation publishes the item
    Then the publish is refused with code "approval-required"
    And the item is not published
    And one open hard gate review request is about the item

  Scenario: Trying again does not pile up requests
    Given a saved draft article on a site that requires approval to publish
    And an automation has tried to publish the item
    When an automation publishes the item
    Then the publish is refused with code "approval-required"
    And one open hard gate review request is about the item

  Scenario: A person approving the request lets the next publish through
    Given a saved draft article on a site that requires approval to publish
    And an automation has tried to publish the item
    When a person approves the review request
    And an automation publishes the item
    Then the item is published

  Scenario: Approval covers only the words that were approved
    Given a saved draft article on a site that requires approval to publish
    And an automation has tried to publish the item
    And a person approves the review request
    When the article text changes
    And an automation publishes the item
    Then the publish is refused with code "approval-required"
    And there are 2 review requests

  Scenario: A rejected version stays unpublished until its text changes
    Given a saved draft article on a site that requires approval to publish
    And an automation has tried to publish the item
    When a person rejects the review request
    And an automation publishes the item
    Then the publish is refused with code "approval-rejected"
    And there is 1 review request

  Scenario: An editor publishing from the console is not blocked by their own gate
    Given a saved draft article on a site that requires approval to publish
    When a signed-in editor publishes the item from the console
    Then the item is published
    And no review request exists

  Scenario: An editor's publish settles a request that was already waiting
    Given a saved draft article on a site that requires approval to publish
    And an automation has tried to publish the item
    When a signed-in editor publishes the item from the console
    Then the item is published
    And no review request is open

  Scenario: A call that is not a signed-in editor is gated even through the content actions
    Given a saved draft article on a site that requires approval to publish
    When the content actions publish the item without a signed-in editor
    Then the content actions refuse with code "approval-required"

  Scenario: The console's signed-in editor publishes through the content actions
    Given a saved draft article on a site that requires approval to publish
    When the content actions publish the item for a signed-in editor
    Then the content actions report the item published

  Scenario: A dry run says what would happen and writes nothing
    Given a saved draft article on a site that requires approval to publish
    When the operator previews publishing the item
    Then the publish is refused with code "approval-required"
    And no review request exists

  Scenario: Unpublishing is never gated
    Given a published article on a site that requires approval to publish
    When the operator unpublishes the item
    Then the item is not published

  Scenario: The operator reads and sets the setting
    Given a site with no publish gate setting
    When an operator sets the publish approval setting to "required"
    Then the publish approval setting reads "required"
    When an operator sets the publish approval setting to "not_required"
    Then the publish approval setting reads "not_required"

  Scenario: The setting only takes its two values
    Given a site with no publish gate setting
    When an operator tries to give the publish approval setting the value "sometimes"
    Then the setting is refused
