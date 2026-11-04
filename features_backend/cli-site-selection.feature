Feature: An editor picks a signed-in site and runs any newsroom command from any directory
  A person who has signed in with `papyrus login` should not need a file from the Amplify
  build, an endpoint variable, a tenant variable or an AWS login to work on a site. The CLI
  chooses the site in a fixed order: the site the person names, then the endpoint variable,
  then the site the working directory declares, then an Amplify outputs file, then the only
  signed-in site. Several signed-in sites with no choice is an error that lists them; the CLI
  never guesses. The tenant a site belongs to is published by the site itself in a second
  public file, so the person never types it. Nothing here touches a real site, browser,
  keychain or network.

  Scenario: One signed-in site is enough, with no outputs file anywhere
    Given the person is signed in to "a.anth.us" only
    And the working directory has no Amplify outputs file
    When a command asks for the site's GraphQL endpoint
    Then the endpoint is the one "a.anth.us" published

  Scenario: Nothing signed in and no file says to log in
    Given the person is signed in to no site
    And the working directory has no Amplify outputs file
    When a command asks for the site's GraphQL endpoint
    Then the command fails with a message that names "papyrus login"
    And the message does not tell a deployed site's editor to run a sandbox first

  Scenario: A site named on the command line beats everything the directory holds
    Given the person is signed in to "a.anth.us" and "b.anth.us"
    And the working directory has an Amplify outputs file for another backend
    When a command asks for the site's GraphQL endpoint after the person names "b.anth.us" with the leading site flag
    Then the endpoint is the one "b.anth.us" published

  Scenario: A site named by the site variable is the same choice
    Given the person is signed in to "a.anth.us" and "b.anth.us"
    When a command asks for the site's GraphQL endpoint after the person sets the site variable to "a.anth.us"
    Then the endpoint is the one "a.anth.us" published

  Scenario: A named site the person has not signed in to says how to sign in
    Given the person is signed in to "a.anth.us" only
    When a command asks for the site's GraphQL endpoint after the person names "c.anth.us" with the leading site flag
    Then the command fails with a message that names "papyrus login c.anth.us"

  Scenario: A named site that disagrees with the endpoint variable is refused
    Given the person is signed in to "a.anth.us" and "b.anth.us"
    And the endpoint variable names the backend of "b.anth.us"
    When a command asks for the site's GraphQL endpoint after the person names "a.anth.us" with the leading site flag
    Then the command fails with a message saying the endpoint variable names a different backend

  Scenario: Several signed-in sites and no choice is an error that lists them
    Given the person is signed in to "a.anth.us" and "b.anth.us"
    And the working directory has no Amplify outputs file
    When a command asks for the site's GraphQL endpoint
    Then the command fails with a message listing "a.anth.us" and "b.anth.us"
    And the message tells the person to name one with the leading site flag
    And no site was chosen

  Scenario: The site a checkout declares is used when the person is signed in to it
    Given the person is signed in to "a.anth.us" and "b.anth.us"
    And the working directory is the checkout of "b.anth.us"
    When a command asks for the site's GraphQL endpoint
    Then the endpoint is the one "b.anth.us" published

  Scenario: A checkout of a site the person has not signed in to is never answered with a different site
    Given the person is signed in to "a.anth.us" only
    And the working directory is the checkout of "b.anth.us"
    When a command asks for the site's GraphQL endpoint
    Then the command fails with a message that names "papyrus login b.anth.us"

  Scenario: A present outputs file is used when nothing was chosen
    Given the person is signed in to "a.anth.us" only
    And the working directory has an Amplify outputs file for another backend
    When a command asks for the site's GraphQL endpoint
    Then the endpoint is the one in the outputs file

  Scenario: An operator who chose IAM is never sent to a signed-in site
    Given the person is signed in to "a.anth.us" only
    And the operator chose the IAM lane
    And the working directory has no Amplify outputs file
    When a command asks for the site's GraphQL endpoint
    Then the command fails with a message that names "papyrus login"
    And no signed-in site was used

  Scenario: A process that is not the CLI never reads the sign-in registry
    Given the person is signed in to "a.anth.us" only
    And the process is a Lambda, which never installs the site selection
    When a command asks for the site's GraphQL endpoint
    Then no signed-in site was used

  Scenario: The bucket and identity pool of a file for another backend are not used for the chosen site
    Given the person is signed in to "a.anth.us" and "b.anth.us"
    And the working directory has an Amplify outputs file for another backend
    When the bucket and identity pool are read after the person names "b.anth.us" with the leading site flag
    Then neither is taken from that file

  Scenario: The tenant comes from the site the person is signed in to
    Given the person is signed in to "a.anth.us" only
    And "a.anth.us" publishes the tenant "machines-on-machines" in its site file
    When the person opens an authoring client
    Then the client is scoped to the tenant "machines-on-machines"
    And the person set no tenant variable and passed no tenant option

  Scenario: A person who signed in before the site file existed does not have to sign in again
    Given the person is signed in to "a.anth.us" only
    And the CLI kept no site file for "a.anth.us"
    And "a.anth.us" publishes the tenant "machines-on-machines" in its site file
    When the person opens an authoring client
    Then the client is scoped to the tenant "machines-on-machines"
    And the CLI kept the site file for next time

  Scenario: An explicit tenant option beats the site's tenant
    Given the person is signed in to "a.anth.us" only
    And "a.anth.us" publishes the tenant "machines-on-machines" in its site file
    When the person opens an authoring client with the tenant option "other-tenant"
    Then the client is scoped to the tenant "other-tenant"

  Scenario: The tenant variable beats the site's tenant
    Given the person is signed in to "a.anth.us" only
    And "a.anth.us" publishes the tenant "machines-on-machines" in its site file
    And the person set the tenant variable to "other-tenant"
    When the person opens an authoring client
    Then the client is scoped to the tenant "other-tenant"

  Scenario: A site that has not been upgraded publishes no site file and nothing fails
    Given the person is signed in to "a.anth.us" only
    And "a.anth.us" publishes no site file
    When the person opens an authoring client
    Then the client has no tenant
    And nothing failed

  Scenario: A command that must read every row is not scoped to the site's tenant
    Given the person is signed in to "a.anth.us" only
    And "a.anth.us" publishes the tenant "machines-on-machines" in its site file
    When the person opens an authoring client for a command that reads every row
    Then the client has no tenant

  Scenario: The sign-in file is not given any new field
    Given the person is signed in to "a.anth.us" only
    When the person asks which public files the CLI reads from "a.anth.us"
    Then the sign-in file is "/.well-known/papyrus-cli.json" and the site file is "/.well-known/papyrus-site.json"

  Scenario: An old CLI is told to upgrade when a command is unknown and the site is newer
    Given the person is signed in to "a.anth.us" only
    And "a.anth.us" publishes that it runs Papyrus 99.0.0
    When the person runs a command this CLI does not know
    Then the failure still says the command is unsupported
    And it names "a.anth.us" and version 99.0.0 and the upgrade command

  Scenario: An unknown command from a current CLI gets no hint
    Given the person is signed in to "a.anth.us" only
    And "a.anth.us" publishes that it runs Papyrus 0.0.1
    When the person runs a command this CLI does not know
    Then the failure says only that the command is unsupported

  Scenario: A version never fails a command
    Given the person is signed in to "a.anth.us" only
    And "a.anth.us" publishes no site file
    When the person runs a command this CLI does not know
    Then the failure says only that the command is unsupported

  Scenario: Logging in to a newer site warns that the CLI is older
    Given "a.anth.us" publishes login metadata and a site file saying it runs Papyrus 99.0.0
    When the person runs "papyrus login a.anth.us"
    Then the login succeeds
    And a warning on standard error says this CLI is older than "a.anth.us" and how to upgrade

  Scenario: The remote approval URL is shown at once even when output is redirected
    Given the person is signed in to no site
    When a remote login prints its approval URL
    Then the line was flushed immediately
