Feature: Static projection of published content
  A site is a projection of its published content. Projecting everything writes
  the files a full Markus build writes. Projecting one item writes only the
  pages that depend on it, in an order that never leaves a link to a missing page.

  Scenario: Projecting everything equals the full build
    Given the projection fixture site is published
    When I project everything to a local directory
    Then the projected directory is identical to the full build of the fixture content

  Scenario: Projecting everything equals the full build when the home page is generated
    Given the projection fixture site is published without a hand-authored home page
    When I project everything to a local directory
    Then the projected directory is identical to the full build of the fixture content

  Scenario: Every page carries the one version token computed from the static files
    Given the projection fixture site is published
    When I project everything to a local directory
    Then every projected page links its assets with the version token of the static files

  Scenario: Publishing items one at a time converges on the full build
    Given the projection fixture items are saved as drafts
    When the static files are projected
    And each fixture item is published and projected in turn
    Then the projected directory is identical to the full build of the fixture content

  Scenario: Retitling an article updates every page that lists it
    Given the projection fixture site is published and projected
    When the article "alpha" is retitled "Alpha Prime" and projected
    Then the projected directory is identical to the full build of the fixture content

  Scenario: Unpublishing an article removes its page and its links
    Given the projection fixture site is published and projected
    When the article "beta" is unpublished and projected
    Then the projected directory is identical to the full build of the fixture content
    And the page "articles/beta.html" does not exist

  Scenario: A published item is written before the pages that link to it
    Given the projection fixture site is published and projected
    When the article "gamma-note" is retitled "Gamma Prime" and projected
    Then "articles/gamma-note.html" is written before "index.html"

  Scenario: An unpublished item is deleted after the pages that link to it are rewritten
    Given the projection fixture site is published and projected
    When the article "beta" is unpublished and projected
    Then "index.html" is written before "articles/beta.html" is deleted

  Scenario: Item pages record the published version they were rendered from
    Given the projection fixture site is published and projected
    When the article "alpha" is retitled "Alpha Prime" and projected
    Then the page "articles/alpha.html" was written with the published version of "alpha"

  Scenario: A rendering failure writes nothing
    Given the projection fixture site is published and projected
    When the article "alpha" is retitled "Alpha Prime" and projected with a projector that fails to render
    Then the projection raised an error
    And no page was written by that projection

  Scenario: Aliases become redirects and are removed with the item
    Given the projection fixture site is published and projected with a redirect store
    When the article "alpha" gains the alias "old/alpha" and is projected
    Then the redirect store maps "/old/alpha" to "/articles/alpha.html"
    When the article "alpha" is unpublished and projected
    Then the redirect store no longer maps "/old/alpha"
