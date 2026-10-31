Feature: An Alexa skill can link to a person's Google sign-in on the site's own user pool
  When a site turns account linking on, the alexa plugin adds one dedicated app client to the site's own Cognito user pool. Alexa
  signs a person in through Google and the authorization code flow, then refreshes the session on its own. Without account linking
  the site's pool is untouched. These scenarios use synthesized templates; nothing is deployed.

  Scenario: The client exists only when the site turns account linking on
    When the alexa plugin is wired for a site with account linking off
    Then the user pool gets no Alexa client, no environment variables and no linking outputs
    And with account linking on the pool gets exactly one Alexa client

  Scenario: Account linking needs the Amazon vendor ID
    When a site turns account linking on without a vendor ID or with a malformed one
    Then the settings are refused before anything deploys

  Scenario: The client admits only Google and the code flow
    When the alexa plugin is wired for a site with account linking on
    Then the client allows the Google provider, the code flow and nothing else
    And password, SRP and custom authentication are left off
    And the client is created after the Google provider

  Scenario: Alexa authenticates with a secret and refreshes its own tokens
    When the alexa plugin is wired for a site with account linking on
    Then the client has a generated secret that the template stores nowhere
    And refresh tokens last a year while access and ID tokens last an hour

  Scenario: The callbacks are Amazon's account-linking redirects
    When the alexa plugin is wired for a site with account linking on
    Then the client's callback URLs are Amazon's three regional redirects for the vendor ID

  Scenario: The function and the outputs learn about the client
    When the alexa plugin is wired for a site with account linking on
    Then the function receives the user pool ID and the client ID
    And the outputs carry the pool, the client and the hosted sign-in domain beside the function ARN

  Scenario: A site without Google sign-in cannot turn linking on
    When account linking is on but the site has no Google identity provider
    Then the deploy is refused with a clear reason
