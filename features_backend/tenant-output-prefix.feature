Feature: A projection can write under an output prefix
  Many sites will share one bucket, each in its own folder, so the projection needs to be told which folder is
  its own. The output prefix is a relative folder name such as "sites/alpha/". It is separate from urls.basePath,
  which changes the addresses a reader sees: the prefix changes only where the files are stored, so a page keeps
  the same links, canonical address and sitemap whichever folder it is stored in. Every file the projection writes
  goes under the prefix: pages, listings, public data, search files, agent files, the sitemap, robots.txt, the
  not-found page and the projection's own state files. A writer with a prefix refuses to write, read or delete a
  key outside its folder. A site with no prefix, which is every dedicated site today, writes exactly where it
  always has.

  Background:
    Given a published standard site with a story

  Scenario: A dedicated site's keys do not change
    Given a site with no output prefix
    When it is projected
    Then the key listing is byte-identical to before

  Scenario: A prefixed projection writes only under its prefix
    Given output prefix "sites/alpha/"
    When the prefixed site is projected
    Then every key starts with "sites/alpha/"

  Scenario: The prefix moves the files and changes nothing in them
    Given output prefix "sites/alpha/"
    When the prefixed site is projected
    Then the prefixed site holds the same pages as the unprefixed site, each with identical content
    And the prefixed site holds the not-found page, robots.txt and the sitemap under its prefix

  Scenario: A prefixed writer refuses a key outside its prefix
    Given output prefix "sites/alpha/"
    When a key that climbs out of the prefix is written
    Then the writer refuses it and nothing is written outside "sites/alpha/"

  Scenario: Two sites in one folder tree do not see each other
    Given output prefix "sites/alpha/"
    And another site already stored under "sites/beta/"
    When the prefixed site is projected
    Then the projection lists only the keys under "sites/alpha/"
    And "sites/beta/" is untouched
