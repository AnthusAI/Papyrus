Feature: A site adds a news source without an engine release
  A feed monitor reads an RSS or Atom feed. The engine knows a few hosts by name. A site that wants another source names it in the monitor's own
  configuration, which is data an administrator edits: the source's name goes in the config and any public https host is then accepted. The engine still
  refuses what is never safe to read: an address that is not https, one with credentials or a fragment or an odd port, an IP address, localhost or an
  internal name. The name the config gives is the name shown for the source. A host the engine knows needs no name. Kinds of source that need their own
  reader still need code; a feed needs none.

  Scenario: A feed on a host the engine does not know is accepted when the config names the source
    Given a feed monitor config for "https://feeds.satirejournal.com/rss.xml"
    When the config also names the source "Satire Journal"
    Then the config is accepted and keeps the source name "Satire Journal"
    And the source is shown as "Satire Journal"

  Scenario: The same address without a name is refused
    Given a feed monitor config for "https://feeds.satirejournal.com/rss.xml"
    Then the config is refused saying the monitor's config must name the source

  Scenario: A built-in host needs no name
    Given a feed monitor config for "https://rss.arxiv.org/rss/cs.CR"
    Then the config is accepted with no source name

  Scenario Outline: A name never makes an unsafe address acceptable
    Given a feed monitor config for "<address>"
    When the config also names the source "Anything"
    Then the config is refused

    Examples:
      | address                                        |
      | https://localhost/rss                          |
      | https://127.0.0.1/rss                          |
      | https://10.0.0.5/rss                           |
      | https://intranet/rss                           |
      | https://printer.local/rss                      |
      | http://feeds.satirejournal.com/rss.xml         |
      | https://feeds.satirejournal.com:8443/rss.xml   |

  Scenario: The fetch reads only what the config allowed
    Given a feed monitor config for "https://feeds.satirejournal.com/rss.xml"
    Then reading that address without the source's name is refused before any request
