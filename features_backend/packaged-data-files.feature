Feature: The PyPI wheel carries the data files the commands read at run time
  The unattended cloud knowledge run installs papyrus-newsroom from PyPI into a
  container, where there is no repository checkout and no corpora/ directory. The
  default configuration files that commands read at run time (the semantic relation
  types, the publication doctrine, the required procedures, the analysis profiles,
  the semantic concepts, the newsroom sections, the lexical steering and the steering
  config) therefore ship inside the papyrus_content package under data/corpora/ and
  are found through importlib.resources. In a checkout, a file under the repository's
  corpora/ directory still wins, so an operator or a publication can override a
  default by editing it in place.

  Scenario: The built wheel contains every default configuration file
    Given the wheel built from this checkout
    Then the wheel contains the file papyrus_content/data/corpora/papyrus-semantic-relation-types.yml
    And the wheel contains every default configuration file that the code names

  Scenario: Commands find the data when run from an installed package
    Given the wheel built from this checkout
    When the wheel is installed away from the checkout and the relation types are loaded
    Then the relation types file comes from the installed package
    And the relation types load

  Scenario: A checkout file overrides the packaged default
    Given a checkout with its own corpora/papyrus-steering.yml
    Then the steering config resolves to the checkout file
    When that checkout file is removed
    Then the steering config resolves to the packaged default

  Scenario: The wheel depends on the exact shared login library release
    Given the wheel built from this checkout
    Then the wheel requires cli-login at exactly version 0.3.0, with the Linux extra on Linux

  Scenario: Code that Lambda functions run works without the login library
    The Lambda bundles ship papyrus_content but not cli-login, which only the CLI
    needs. Release 5.61.0 failed on every site because a GraphQL request from a
    Lambda function imported it.
    Given a Python process that cannot import cli_login and has no signed-in user session
    When it imports the content-actions handler and signs a GraphQL request with IAM
    Then the request carries an IAM signature
    And cli_login was never imported
