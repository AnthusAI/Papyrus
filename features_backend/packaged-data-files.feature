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
    Then the wheel requires cli-login at exactly version 0.4.1, with the Linux extra on Linux

  Scenario: A plain install can save a story version
    The documented install is pipx install papyrus-newsroom, with no extras. Saving
    a story version derives bodyIr with Markus, so Markus must be a base
    requirement of the wheel, not only part of the markus extra. Release 5.83.0
    failed with No module named markusmd on a plain install. The package smoke
    workflow also installs the checkout with no extras and derives a body.
    Given the wheel built from this checkout
    Then the wheel requires anthus-markus for every install, not only for an extra

  Scenario: A plain install can save and repair pictures
    The picture commands are for an ordinary editor install: stories save-version
    with --images, stories repair-image-paths and ops content renditions. They reach
    the site's media bucket through boto3 and read image sizes with Pillow. Release
    5.86.0 printed the repair plan and then failed with No module named boto3 on a
    plain install, because both were only in the markus extra. Both are base
    requirements of the wheel now, and the package smoke workflow installs the
    checkout with no extras and builds the same clients those commands build.
    Given the wheel built from this checkout
    Then the wheel requires boto3 for every install, not only for an extra
    And the wheel requires Pillow for every install, not only for an extra

  Scenario: Code that Lambda functions run works without the login library
    The Lambda bundles ship papyrus_content but not cli-login, which only the CLI
    needs. Release 5.61.0 failed on every site because a GraphQL request from a
    Lambda function imported it.
    Given a Python process that cannot import cli_login and has no signed-in user session
    When it imports the content-actions handler and signs a GraphQL request with IAM
    Then the request carries an IAM signature
    And cli_login was never imported
