@brand-agnostic
Feature: An editor can list only the videos among thousands of References
  The Newsroom References page has a row of Medium buttons, All and Videos, beside Reviewed. Videos lists only the References whose address is a
  video, newest first, read from the medium index one vote partition at a time and never from the whole table. It combines with Reviewed, so the
  pending videos are two clicks away: Videos, with Reviewed No (the page's default). The choice is in the page address, as medium=video, so a link
  opens the same list; it is not saved in the browser. Each button has a Lucide icon and a word, a flat tone, rounded corners and no border, and
  nothing scrolls sideways at phone width. A Reference whose medium is unknown is not in the index, so it is listed under All and never under
  Videos. These scenarios use a synthetic site in an isolated browser at 375 and 1440 pixels and never touch production.

  Scenario: Videos lists only the pending videos, from the medium partitions alone
    Given a synthetic site with pending, accepted and rejected videos in two corpora, a starred video, an archived video and an article
    When the editor chooses Videos with Reviewed No
    Then only the pending videos are listed, newest first, across both corpora
    And the page read the pending medium partition of each corpus and no other index
    And the address names medium=video and keeps the rest of the address
    And the saved Sort is unchanged, although Newest shows as chosen because the medium index is by arrival

  Scenario: Videos combines with every Reviewed choice, with stars and with Captured
    Given a synthetic site with pending, accepted and rejected videos in two corpora, a starred video, an archived video and an article
    When the editor chooses Videos and then each Reviewed choice, a minimum of three stars, and Captured Yes
    Then Reviewed Accepted lists the accepted videos and Reviewed Yes lists the accepted and rejected ones
    And a minimum of three stars lists only the starred video
    And Captured Yes with nothing captured says in words that there are no videos, with a button to show all media

  Scenario: Predictions cannot order a medium and a search does not use one
    Given a synthetic site with pending, accepted and rejected videos in two corpora, a starred video, an archived video and an article
    When the editor opens the page on medium=video and chooses Predictions, or searches
    Then choosing Predictions goes back to All and removes the medium from the address
    And the Medium row is out of the way while a search is open

  Scenario: The buttons are words and icons in flat tones
    Given a synthetic site with pending, accepted and rejected videos in two corpora, a starred video, an archived video and an article
    When the editor looks at the Medium row at 375 and 1440 pixels
    Then All and Videos each have a Lucide icon and a word, there is no drop-down and no border, and nothing scrolls sideways
