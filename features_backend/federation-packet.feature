Feature: Federation review packet per site
  Before the Papyrus CLI callbacks may be added to a site's registered Prospectus
  federation client, Prospectus re-reviews that client. The reviewer needs one
  packet per site that states exactly what is deployed. An operator runs a
  read-only script against the site's Cognito user pool and gets a Markdown
  packet outside the repository, because it holds client and pool ids.

  Scenario: The packet for a site lists the client's callbacks, provider, flows, scopes and validity from read-only describes
    Given a site whose federation client is Google-only with two callback URLs
    When the operator generates the federation packet for that site outside the repository
    Then the packet lists the deployed callback URLs and the callback URLs after the CLI task
    And the packet names the Google provider with its scopes and attribute mapping
    And the packet states the code flow, the scopes and the token validity
    And the packet states that sign-in is Google-only
    And the packet never contains the Google client secret

  Scenario: The packet refuses to be written inside the repository
    Given a site whose federation client is Google-only with two callback URLs
    When the operator generates the federation packet for that site inside the repository
    Then the script refuses and no packet is written

  Scenario: A site whose client allows a non-Google provider is reported as not Google-only
    Given a site whose federation client also allows a non-Google provider
    When the operator generates the federation packet for that site outside the repository
    Then the packet states that sign-in is not Google-only
    And the script exits with a failure status
