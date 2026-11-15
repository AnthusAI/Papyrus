Feature: The procedure runner is deployed by the release, from this commit, for every site
  Server-side automations (translation, Stage Bots, Run now) run in the procedure runner. Its image is built by the release from the code in Git and
  its role may call each site's API, so no site waits on a hand-built image or a hand-edited grant.

  Scenario: The image tag is a hash of what the image is built from
    Given the files the runner image is built from
    When one of them changes
    Then the image tag changes
    And an unchanged tree has the same tag

  Scenario: The release builds the image and passes it to the runner stack
    Given the release configuration
    Then the runner stack builds its image with the image build script and receives it as ImageUri
    And the runner stack comes after the monitoring stack it reads its API ids from

  Scenario: The runner may call every site's API without any API id in Git
    Given the runner stack template
    Then its role may call every site's API
    And the template names no API id

  Scenario: The existing repository is imported, never recreated
    Given the release configuration
    Then the repository stack imports the existing repository and retains it

  Scenario: Nothing builds or pushes the image by hand
    Given the release configuration
    Then the hand build script no longer exists
