Feature: The Markdown twin of an authored page says what the page shows
  A page written as a file (a "pages" entry with a source) is a template: it places bands, columns and buttons,
  and includes that draw lists of References, conversations, stories or a site's own blocks. Its Markdown twin
  (/x/index.md, also the home page and a section front page) is what a reader following "View as Markdown" and an
  agent receive, so it carries the page's content: each include becomes a Markdown list of titles and links, a button
  becomes a link, an island becomes its summary, and no template directive reaches the reader. The twin lists the same
  items, in the same order, as the page, because it reads them through the same selection. It carries only the
  title, address and standing that the page publishes, nothing private. When the data an include draws changes,
  the twin is rewritten by the same path that rewrites the page. An article is not a template: its twin stays its
  Markus source as written.

  Background:
    Given a site with accepted and recommended References and two conversations
    And the page "wire" titled "The wire" is written as
      """
      ::band{size="bare"}
      ::include{kind="references" select="recent" count="2" heading="Recently accepted" more="/tools/"}

      ::include{kind="references" select="recent" count="3" empty="Nothing has been accepted yet."}

      ::include{kind="references" select="recommended" count="2" empty="Nothing is waiting for an editor."}

      ::include{kind="threads" select="recent" count="5" empty="No conversations yet."}

      ::include{kind="listing" count="2"}

      ::button{href="/tools/" label="All tools"}
      """

  Scenario: The twin lists the References, conversations and stories the page shows
    When the page-twin site is projected
    Then the agent page "wire/index.md" says "## Recently accepted"
    And the agent page "wire/index.md" says "- [Accepted eight](https://www.example.org/posts/8)"
    And the agent page "wire/index.md" says "- [Accepted seven](https://www.example.org/posts/7)"
    And the agent page "wire/index.md" says "[More](https://almanac.example.org/tools/)"
    And the agent page "wire/index.md" says "- [Is this worth adopting?](https://almanac.example.org/conversations/aaaaaaaaaaaa/) (2 messages)"
    And the agent page "wire/index.md" says "- [Fungi Underground](https://almanac.example.org/fungi.md)"
    And the agent page "wire/index.md" says "[All tools](https://almanac.example.org/tools/)"

  Scenario: No template directive reaches the twin
    When the page-twin site is projected
    Then the agent page "wire/index.md" has no page directive
    And the agent page "llms-full.txt" has no page directive

  Scenario: A Reference the page shows once is not repeated by a later include, as on the page
    When the page-twin site is projected
    Then the agent page "wire/index.md" lists "Accepted eight" once
    And the agent page "wire/index.md" lists "Accepted six" once

  Scenario: A Reference no editor has accepted is labelled as such
    When the page-twin site is projected
    Then the agent page "wire/index.md" says "- [Pending high](https://www.example.org/posts/10) (Recommended by Cyclotron, not yet accepted)"

  Scenario: An include with nothing to show says its empty text
    Given the References snapshot is empty
    When the page-twin site is projected
    Then the agent page "wire/index.md" says "Nothing has been accepted yet."
    And the agent page "wire/index.md" says "Nothing is waiting for an editor."
    And the agent page "wire/index.md" has no page directive

  Scenario: The twin holds nothing private
    When the page-twin site is projected
    Then the agent page "wire/index.md" does not say "Ada Author"
    And the agent page "wire/index.md" does not say "Summary of post"
    And the agent page "wire/index.md" does not say "confidence"
    And the agent page "wire/index.md" carries no identifier of a person

  Scenario: llms-full.txt carries the same lists
    When the page-twin site is projected
    Then the agent page "llms-full.txt" says "- [Accepted eight](https://www.example.org/posts/8)"

  Scenario: The twin is rewritten with the page when the snapshot changes
    Given the page-twin site is projected
    When the title of the newest accepted Reference changes in the snapshot and the pages that read it are rewritten
    Then the agent page "wire/index.html" says "Accepted eight, retitled"
    And the agent page "wire/index.md" says "- [Accepted eight, retitled](https://www.example.org/posts/8)"
    And the agent page "llms-full.txt" says "Accepted eight, retitled"

  Scenario: A site's own block reaches the twin as a list of titles and links
    Given a site with the stories "a1" and "a2" and a block hook "proof-strip" that draws a card for each
    And the page "proof" titled "Proof" is written as
      """
      ::band{size="bare"}
      # Proof

      ::include{kind="block" name="proof-strip" depends="posts"}
      """
    When the page-twin site is projected
    Then the agent page "proof/index.md" says "## Proof strip"
    And the agent page "proof/index.md" says "- [A1](https://example.org/posts/a1.html)"
    And the agent page "proof/index.md" says "- [A2](https://example.org/posts/a2.html)"
    And the agent page "proof/index.md" does not say "2026-01-02"
    And the agent page "proof/index.md" has no page directive

  Scenario: The home page twin says what the home page shows
    Given a site whose home item is written as
      """
      ::band{size="hero"}
      # Welcome

      Words here.

      ::button{href="/start/" label="Start"}
      """
    When the page-twin site is projected
    Then the agent page "index.md" says "# Welcome"
    And the agent page "index.md" says "[Start](https://example.org/start/)"
    And the agent page "index.md" has no page directive

  Scenario: An article twin stays its Markus source as written
    Given a site with an article "story" written as
      """
      ::band{size="bare"}
      # Story

      ::button{href="/x/" label="Go"}
      """
    When the page-twin site is projected
    Then the agent page "story.md" says "::band{size="bare"}"
    And the agent page "story.md" says "::button{href="/x/" label="Go"}"
