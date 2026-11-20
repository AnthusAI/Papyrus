@backend @home-page
Feature: A Reference change re-projects exactly the list pages that show it
  The site's Reference list pages (Videos, Findings, each section's videos) are drawn from the home-page snapshot by the debounced
  home-page-snapshot run. That run must bring every list page that shows a changed Reference up to date in the same pass, with no hand
  purge and no rule for any one page, and it must leave every other page alone: rendering, writing and serving a page that did not change
  costs work and edge requests for nothing. So a page's input digest holds what its lists place (the public record of each Reference shown,
  and for a paged list the key its "Load more" link starts from), not the bytes of the whole snapshot file. A change that a page does not show
  never makes that page stale; the chunk files after a paged list's first page already work this way.

  Background:
    Given a site whose list pages show accepted videos, videos filed under Music, videos filed under Art and accepted findings
    And the snapshot was built by a full read

  Scenario: A video's new picture reaches the Videos list and its section's list in the same run
    The thumbnail worker writes the stored copy's path onto the Reference; the stream trigger lists that Reference and the debounced run reads it again.
    When the newest Music video gets its stored thumbnail and the snapshot run reads it again
    Then the snapshot file carries the video's picture
    And the Videos page and the Music videos page are re-projected, with their Markdown twins, and show the picture
    And the Art videos page and the Findings page are not re-projected
    And no chunk file of a paged list is re-projected

  Scenario: A picture for a video past the Videos list's first page rewrites the chunk that shows it
    When an older Art video gets its stored thumbnail and the snapshot run reads it again
    Then only chunk files of the Videos list are re-projected among the paged lists
    And the Art videos page is re-projected and the Videos page is not

  Scenario: A change that no list page shows re-projects no page
    A pending Reference the Cyclotron recommends is public, so the snapshot file changes, but none of these lists places it.
    When a recommended Reference is retitled and the snapshot run reads it again
    Then the snapshot file carries the new title
    And no page is re-projected

  Scenario: The pages the run re-projects are byte for byte what a full rebuild draws
    When the newest Art video gets its stored thumbnail and the snapshot run reads it again
    Then every list page is what a full projection from the new snapshot draws

  Scenario: A section front that shows a Reference grid is re-projected by the same run
    A section front with index.references draws a grid from the snapshot like any list page, so the snapshot run must count it among its readers.
    Given a site whose Essays section front shows the two newest accepted Essays References
    When a Reference on that grid is retitled and the snapshot file is written
    Then the Essays front is re-projected and shows the new title
    When a Reference filed under Notes is retitled and the snapshot file is written
    Then the Essays front is not re-projected
