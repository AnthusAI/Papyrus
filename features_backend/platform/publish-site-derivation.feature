Feature: The CLI derives the publication kind and content-actions function from the site
  An operator shell has no PAPYRUS_PUBLICATION_KIND or PAPYRUS_CONTENT_ACTIONS_FUNCTION.
  The deployed backend publishes both as custom outputs in amplify_outputs.json, so
  publish and unpublish re-project an s3-projection site with no environment set up.

  Scenario: The outputs name an s3-projection publication and its function
    Given a site whose amplify_outputs.json declares an s3-projection publication with function "site-content-actions"
    And no publication environment variables are set
    Then projection is enabled
    And the projection is scheduled on "site-content-actions"

  Scenario: Environment variables win over the outputs
    Given a site whose amplify_outputs.json declares an s3-projection publication with function "site-content-actions"
    And the environment names the function "env-content-actions"
    Then the projection is scheduled on "env-content-actions"

  Scenario: A site without a publication output is not projected
    Given a site whose amplify_outputs.json declares no publication
    And no publication environment variables are set
    Then projection is not enabled

  Scenario: A missing amplify_outputs.json is not an error
    Given a site with no amplify_outputs.json
    And no publication environment variables are set
    Then projection is not enabled
