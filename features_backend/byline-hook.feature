Feature: A site's byline hook gives an article's page and its Markdown twin the same byline
  Core writes an article's byline from its authors: the names, each a link when the author has a url. A site
  may have a rule of its own for how a story is credited (for example, "By various bots and Ryan Porter" for a story
  that bots drafted and a person edited), and then the page and the Markdown twin at /x/index.md must not
  disagree about who wrote it. The site's hooks module may define byline(entry), which returns the complete byline
  text as plain text. Core shows that text in the byline of the article page (when the site has item bylines on)
  and in the "By ..." line of the Markdown twin, and escapes it for HTML. A site without the hook, or a hook that
  returns nothing for an article, keeps the authors' names, with their links.

  Scenario: Without a byline hook, the page and the twin name the authors
    Given a site with item bylines on and no byline hook, and an article "story" by "AI" and "Ryan Porter"
    When the byline site is projected
    Then the agent page "story.html" says "<span class="markus-byline-authors">AI, Ryan Porter</span>"
    And the agent page "story.md" says "By AI, Ryan Porter · Published 2026-10-01"

  Scenario: With a byline hook, the page and the twin carry the hook's text
    Given a site with item bylines on and a byline hook that says "By various bots & Ryan Porter", and an article "story" by "AI" and "Ryan Porter"
    When the byline site is projected
    Then the agent page "story.html" says "<span class="markus-byline-authors">By various bots &amp; Ryan Porter</span>"
    And the agent page "story.html" does not say "<span class="markus-byline-authors">AI"
    And the agent page "story.md" says "By various bots & Ryan Porter · Published 2026-10-01"
    And the agent page "story.md" does not say "By AI"

  Scenario: A byline hook that returns nothing leaves the authors as they are
    Given a site with item bylines on and a byline hook that has nothing to say, and an article "story" by "AI" and "Ryan Porter"
    When the byline site is projected
    Then the agent page "story.html" says "<span class="markus-byline-authors">AI, Ryan Porter</span>"
    And the agent page "story.md" says "By AI, Ryan Porter · Published 2026-10-01"
