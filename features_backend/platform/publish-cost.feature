Feature: Publishing one story costs the same whatever the size of the site
  Publishing a story builds its page and the index pages that list it. Some of
  those pages need every published story's text: llms-full.txt holds the whole
  site, and when something every story page reads changes, every story page is
  built again. Those texts used to be read from the newsroom's records one story
  at a time, two requests a story, so a publish on a site with a hundred and
  sixty stories made more than three hundred requests in a row and took over a
  minute. The text of a published version never changes, so it is now read
  once, when that version is first built (or by the whole-site render), and kept
  beside the pages; a publish reads the story itself, the listing data of the
  site twice (once to plan, once to notice a concurrent publish), and nothing
  else, however many stories the site has. A page rendered again with exactly
  the bytes it already has is neither written again nor purged at the edge.

  Scenario: A publish reads a fixed number of records, whatever the number of published stories
    Given a site with 150 published stories whose pages were built
    And a site with 300 published stories whose pages were built
    When an editor publishes one more story on each site
    Then each build reads at most 3 records one by one and the listing data twice
    And the build on the larger site reads no more than the build on the smaller one
    And neither build reads a whole table of stories
    And llms-full.txt is rebuilt on both sites

  Scenario: The follow-up that rebuilds every story page reads no story one by one
    Given a site with 300 published stories whose pages were built
    When every story page is built again after a change they all read
    Then the rebuild reads the listing data once and no record one by one

  Scenario: An edited story is never shown from an old copy of its text
    Given a site with 10 published stories whose pages were built
    When an editor publishes a new version of one story
    And then publishes another story
    Then llms-full.txt shows the new version's text

  Scenario: Pages whose bytes did not change are neither written nor purged
    Given a site on S3 whose every page reads every story, with 120 published stories whose pages were built
    When an editor publishes one more story on that site
    Then only the pages whose bytes changed are named for the edge purge
    And the pages that came out the same keep the bytes they had
    And a page that came out the same is written again only to record its new inputs digest
