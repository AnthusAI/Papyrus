Feature: The post-deploy render waits for the live schema
  A backend deploy that adds attributes to a model updates the AppSync schema and the Lambda code in the same stack update.
  CloudFormation calls the schema resource complete before the API reliably validates queries against it, so a render that
  already selects a new field can be told the field is undefined, and that fails the whole deploy. The render therefore runs
  only after the data stack, and its first step asks the live API, by introspection, whether it serves every field the
  tools select. It waits while fields are missing. If they never arrive it fails the deploy with a message that names each
  missing field, instead of dropping the field from the query.

  Scenario: The render's stack waits for the stack that holds the content tools
    When the post-deploy render is added next to a content-actions function in the data stack
    Then the render's stack depends on the data stack
    And the render is a single custom resource

  Scenario: A schema that already has every field is rendered at once
    Given a live schema that serves every field the tools select
    When the deploy-render task runs
    Then the live schema was asked 1 time
    And the site was rendered

  Scenario: The render waits for fields that arrive late
    Given a live schema that lacks "Item.versionPublishedAt" and "PublishedItem.versionPublishedBy" for the first 3 questions
    When the deploy-render task runs
    Then the live schema was asked 4 times
    And the site was rendered

  Scenario: A schema that never gets the fields fails the deploy and names them
    Given a live schema that never gets "Item.versionPublishedAt" and "PublishedItem.versionPublishedBy"
    When the deploy-render task runs
    Then the deploy-render task failed saying "Item.versionPublishedAt, PublishedItem.versionPublishedBy"
    And the site was not rendered
