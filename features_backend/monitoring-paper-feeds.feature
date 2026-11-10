Feature: Paper monitors read research feeds and Hugging Face daily papers into one stream of papers
  New shared monitors read research papers, and the shared Cyclotron decides per site. A feed monitor reads any RSS 2.0 or
  Atom feed whose address is in its configuration and whose host the code allows; arXiv is the first. The feed's own
  abstract travels with each paper, so a decision does not need the paper's PDF. A Hugging Face daily papers monitor reads
  the papers the community picks each day. Both name a paper by its arXiv address, so a paper that arrives from both
  sources is one paper and, at intake, one Reference. Like every monitor they read everything new, bound only by time and
  the source's rate limit, never by an invented number.

  Scenario: An RSS feed is read into papers with their abstracts
    Given a feed monitor for the arXiv artificial intelligence RSS feed
    And the feed holds two new papers, a cross-listed paper and two revisions of old papers
    When the feed monitor collects
    Then three papers are recorded and the pass is complete
    And a paper's canonical URL is its arXiv address and its source id is the bare arXiv id
    And a paper carries its title, publication date, authors, categories and abstract
    And the abstract has no arXiv header line and no Abstract label, and its LaTeX is unchanged
    And each paper waits for the router and records that it came from a feed

  Scenario: An Atom feed is read the same way
    Given a feed monitor for the arXiv API Atom feed
    And the feed holds two papers with versioned addresses
    When the feed monitor collects
    Then two papers are recorded and the pass is complete
    And a paper's canonical URL is its arXiv address without the version

  Scenario: arXiv revisions are not news
    Given a feed monitor for the arXiv artificial intelligence RSS feed
    And the feed holds two new papers, a cross-listed paper and two revisions of old papers
    When the feed monitor collects
    Then the new papers and the cross-listed paper are recorded
    And neither revision is recorded

  Scenario: A research organisation's blog feed is read without a description
    Given a feed monitor for the METR RSS feed
    And the feed holds a blog post, a note, an evaluation, a post that links to a paper and a post that links to a page on the site
    When the feed monitor collects
    Then five items are recorded and the pass is complete
    And each item's canonical URL is the feed entry's link, even when the link is on another site or not under blog
    And each item carries its title, publication date and the post's content as its abstract
    And an item's source id comes from the entry's guid

  Scenario: A feed address on a host outside the allowed list is refused
    Given a feed monitor whose address is on a host outside the allowed list
    When the feed monitor collects
    Then the pass is refused because the host is not allowed, before anything is requested
    And nothing is recorded

  Scenario: A feed that declares a DOCTYPE or an ENTITY is refused
    Given a feed monitor for the arXiv security RSS feed
    And the feed declares a DOCTYPE with an ENTITY
    When the feed monitor collects
    Then the pass fails with a note that the XML declaration is not supported
    And nothing is recorded

  Scenario: An empty feed is a complete pass
    Given a feed monitor for the arXiv security RSS feed
    And the feed holds no entries
    When the feed monitor collects
    Then the pass is complete and nothing is recorded

  Scenario: A malformed feed is an error, and the next pass reads it again
    Given a feed monitor for the arXiv security RSS feed
    And the feed is cut off in the middle of an entry
    When the feed monitor collects
    Then the pass fails with a fetch error
    And nothing is recorded

  Scenario: A paper already collected is not collected again
    Given a feed monitor for the arXiv artificial intelligence RSS feed
    And the feed holds two new papers, a cross-listed paper and two revisions of old papers
    And the feed monitor has collected
    When the feed monitor collects again six hours later
    Then no paper is new and the three papers are reported unchanged

  Scenario: Hugging Face daily papers are mapped to arXiv addresses
    Given a Hugging Face papers monitor
    And Hugging Face lists three daily papers picked on two recent days and one earlier day
    When the Hugging Face papers monitor collects
    Then the papers inside the window are recorded and the earlier one is not
    And each paper's canonical URL is its arXiv address
    And a paper keeps its upvotes, comment count, abstract, submitter and organization

  Scenario: One paper from both sources is one canonical address
    Given a feed monitor for the arXiv artificial intelligence RSS feed
    And the feed holds two new papers, a cross-listed paper and two revisions of old papers
    And a Hugging Face papers monitor
    And Hugging Face lists three daily papers picked on two recent days and one earlier day
    When the feed monitor collects
    And the Hugging Face papers monitor collects
    Then the paper both sources list has the same canonical URL and the same source id in both

  Scenario: A decision uses the feed's abstract
    Given a feed monitor for the arXiv artificial intelligence RSS feed
    And the feed holds two new papers, a cross-listed paper and two revisions of old papers
    And the feed monitor has collected
    When the router builds the decision request for a collected paper that has no enrichment summary
    Then the request's summary is the paper's abstract
    And the request's text is the title, the address and the abstract
    And the request names the feed as its source

  Scenario: Each paper monitor has a collect schedule and an hourly route schedule
    Given the paper monitors in the monitoring stack template
    Then papers-arxiv-ai, papers-arxiv-security and papers-huggingface each have a schedule running the collector every 6 hours and a schedule running the router hourly, each naming its monitor
