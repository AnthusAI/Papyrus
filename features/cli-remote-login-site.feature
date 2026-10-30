Feature: A site switches on remote CLI login
  `papyrus login --remote` lets an agent on a machine with no browser sign in: the person approves on their phone.
  It needs a broker, an approval pages function, a Cognito callback and a few lines in the site's public login
  file, and a site gets them only when it turns the feature on. The pages are the cli-login library's own, run by a
  function that the site's Next.js app forwards `/cli/approve` and `/cli/callback` to with IAM. These scenarios use
  synthetic Amplify outputs, synthesized templates and a fake function invoker; nothing is deployed.

  Scenario: Remote login is off unless a site turns it on
    When no site has set the remote CLI login flag
    Then remote CLI login is off for every site, the original production site included
    And no broker, pages function, Cognito callback or output is planned

  Scenario: Switching it on needs the site's origin and its compute role
    When a site turns remote CLI login on
    Then it must name its public https origin and the Amplify compute role that serves its pages

  Scenario: The web client registers the remote callback only for a site that turned it on
    When the site's web client is synthesized with and without the feature
    Then the feature only adds the site's remote callback after the existing callbacks, and never a logout URL

  Scenario: The broker keeps cli-login's security properties
    When a site's broker is synthesized
    Then the public URL takes no credentials and only the pages function's role may invoke the private operations
    And the broker is bounded, reads and writes only its own table, and alarms on its start ceiling and throttling
    And only the site's compute role may invoke the pages function

  Scenario: The CLI, the broker and the pages run the same cli-login release
    When the Lambda bundles are built
    Then the broker and the pages install the exact release that pyproject.toml pins for the CLI
    And the pages function does not import papyrus_content

  Scenario: The site's login file publishes the broker
    When a site that turned it on serves its login file
    Then it names the broker and the site's own remote callback
    But a site that did not publishes no broker, and so does a site whose client lacks the callback

  Scenario: The approval pages are forwarded to the pages function
    When the browser opens the approval page and submits the form
    Then the request reaches the pages function with its method, path, query, cookies and body
    And the page, its redirect and every cookie it sets reach the browser
    And the pages are served at the site root

  Scenario: A site without the feature serves no pages
    When the browser opens the approval page of a site that did not turn it on
    Then the answer is "not found" and nothing is invoked

  Scenario: Failures say little
    When the pages function is unavailable or answers nonsense
    Then the browser is told sign-in is unavailable without any detail
