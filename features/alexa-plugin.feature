Feature: A site puts its published stories on Amazon Alexa
  The `alexa` plugin gives a site one Alexa custom skill: a TypeScript function behind the site's backend, and a skill package
  generated from the site's config. A site gets none of it unless its `papyrus.config.ts` lists the plugin. These scenarios
  use synthesized templates, a fake story source and synthetic Alexa requests; nothing is deployed and no Amazon account is used.

  Scenario: The plugin is absent unless a site lists it
    When a site lists no plugins
    Then the alexa plugin is known to Papyrus
    And nothing about it is resolved, wired or published for that site

  Scenario: The site's settings are checked before anything deploys
    When a site configures the alexa plugin
    Then the invocation name, skill ID, account linking switch and site origin are validated
    And an unknown setting is refused

  Scenario: Only the Alexa service may call the function
    When the alexa plugin is wired for a site
    Then the function accepts invocations from the Alexa service principal only
    And once the skill ID is known the permission carries the skill ID condition

  Scenario: The deploy publishes the endpoint for the skill manifest
    When the alexa plugin is wired for a site
    Then the function ARN is an output the skill package deploy reads
    And the public settings carry no skill ID

  Scenario: The endpoint rejects a request with the wrong skill ID
    Given a site with a configured skill ID
    When a request arrives for a different skill
    Then the endpoint refuses it
    And a request for the configured skill is answered

  Scenario: The endpoint serves nothing until a skill ID is configured
    Given a site without a skill ID
    When any request arrives
    Then the endpoint refuses it

  Scenario: Intents and APL documents are registered in one index each
    When an intent module or an APL document file exists
    Then it is listed in its index, ids are unique and every document is APL

  Scenario: The skill package is generated the same way every time
    When the skill package is generated from a site's settings
    Then the manifest names the endpoint and the interaction model names the invocation name
    And intents are sorted so the same inputs give the same files
    And two modules defining the same intent are refused
