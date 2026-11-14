Feature: A site's deploy keeps its Alexa skill in step with its settings
  The skill package is generated from the site's `alexa` plugin settings and the intent registry, and the site's own deploy syncs
  it to Amazon right after the backend deploy. One Amazon developer account serves every site; its credentials live in SSM.
  The sync never breaks a deploy for a missing prerequisite. These scenarios use fake Amazon, SSM, Lambda and Cognito services:
  nothing is deployed and no network call is made.

  Scenario: The manifest says everything Amazon asks for
    When the skill package is generated for a site that sets an origin
    Then the manifest has the name, summary, description, example phrase, keywords, News category and both icons
    And it names the privacy and terms pages under the site origin unless the settings override them
    And it declares the APL interface, the endpoint and every configured locale

  Scenario: The package is deterministic
    When the skill package is generated twice from the same settings
    Then the bytes are identical and match the committed snapshot

  Scenario: A deploy without Amazon credentials skips cleanly
    When the sync runs and the developer credentials are not in SSM
    Then it logs one line and makes no call to Amazon
    And nothing is written to SSM, so the site deploy carries on

  Scenario: The first sync creates the skill
    When the sync runs for a site that has no skill yet
    Then Amazon is asked to create the skill and the interaction model is uploaded
    And the skill ID is stored in SSM before the upload
    And only that skill may invoke the function afterwards

  Scenario: A deploy with nothing new makes no Amazon call
    When the sync runs again with the same generated content
    Then it makes no call to Amazon
    And a restored unconditional invoke permission is scoped to the skill again

  Scenario: Changed content updates the skill
    When the generated content changes
    Then the manifest and the model are updated and no second skill is created

  Scenario: Account linking is optional and uses the site's Cognito client
    When a site turns account linking on
    Then the sync pushes an authorization code grant against the hosted UI of the site's Cognito pool
    And the client secret is read from Cognito at sync time
    And linking is skipped when the site does not turn it on

  Scenario: The endpoint learns the skill ID from SSM
    When the skill function starts and the skill ID parameter is missing
    Then it serves no request
    And once the parameter exists it serves that skill and remembers the ID

  Scenario: The site build runs the sync after the backend deploy
    When the production build spec of a site is generated
    Then the sync runs after the backend deploy
    And a failed sync never fails the build
