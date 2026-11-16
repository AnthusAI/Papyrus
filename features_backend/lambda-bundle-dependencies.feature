Feature: Every package the page-rendering Lambdas import is in their bundle
  Two Python Lambdas render the site's pages: content-actions, which runs the post-deploy render, and renditions. Each is bundled
  from its own requirements.txt (and, in a site repository, from the same list in its TypeScript definition), not from the
  papyrus-newsroom package's dependencies. So a package that the render code starts importing but that nobody adds to those lists
  is installed everywhere except in the Lambda, and the failure shows up only after a release, when the post-deploy render reports
  "No module named" and CloudFormation rolls the whole backend deploy back. Papyrus 5.128.0 did this with Babel, which the
  standard front end uses to print dates in each language's own format.

  The guard reads the handler's code. It follows every import the handler runs at load time into the Papyrus modules it pulls in,
  and every import anywhere inside the projection package, which is the render code path. For each third-party module it finds, it
  names the package that provides it and checks that package is in the bundle: listed in the requirements, or installed by something
  that is. boto3 and botocore are the only packages left out on purpose, because the Lambda Python runtime provides them. A missing
  package fails the test with a message that names the package, the modules that import it and the files to add it to.

  Scenario Outline: The <bundle> bundle holds every third-party package its render code path imports
    Given the "<bundle>" Lambda bundle and its handler
    When the third-party modules on the handler's import path are collected
    Then every package that provides them is in the bundle

    Examples:
      | bundle          |
      | content-actions |
      | renditions      |

  Scenario Outline: The <bundle> bundle imports Babel and bundles it
    Given the "<bundle>" Lambda bundle and its handler
    When the third-party modules on the handler's import path are collected
    Then the standard front end's import of "babel" is among them
    And the package "Babel" is in the bundle

    Examples:
      | bundle          |
      | content-actions |
      | renditions      |

  Scenario: Babel's locale data comes with the package that is bundled
    Given the package "Babel" that the bundle installs
    Then its files include the locale data for "en", "es" and "zh"

  Scenario: A bundle that lacks a package fails with the package's name
    Given the "content-actions" Lambda bundle and its handler
    And the requirements leave out "Babel"
    When the third-party modules on the handler's import path are collected
    Then the check fails naming the package "Babel" and the file "amplify/functions/content-actions/requirements.txt"

  Scenario Outline: The <bundle> requirements file and the TypeScript list name the same packages
    Given the "<bundle>" Lambda bundle and its handler
    Then the requirements file and the TypeScript list name the same packages

    Examples:
      | bundle          |
      | content-actions |
      | renditions      |
