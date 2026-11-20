Feature: Article pages share one set of page actions on every Papyrus site
  A site turns on the compact page actions by configuration: icon buttons to view the page as Markdown, copy it,
  post it on X or Reddit, and share the web page or its Markdown from a popup. The links work without JavaScript and
  carry only the page title and address, never the article text. A site that does nothing renders exactly as before.
  A site with its own article template places the actions with one call, page.article_actions(), and gets the styles
  it needs even when it does not link the component stylesheet.

  Background:
    Given an agent-readable site with an article "hello" and the page file "pages/models.md" at "topics/models" titled "Decision models" described as "How decisions get made."
    And the page file "pages/models.md" is
      """
      # Decision models

      A model *decides*.
      """
    And the article "hello" has the body
      """
      The body of the article, which must never appear in a post link.
      """

  Scenario: A site that does not opt in keeps the text actions and gains nothing
    When the agent-readable site is projected
    Then the agent page "hello/index.html" says "Copy Markdown"
    And the agent page "hello/index.html" says "View as Markdown"
    And the agent page "hello/index.html" does not say "markus-page-actions-icons"
    And the agent page "hello/index.html" does not say "x.com/intent"
    And the agent page "hello/index.html" does not say "reddit.com/submit"
    And the agent page "hello/index.html" does not say "data-share"
    And the agent site lacks these pages: "_plugins/papyrus-page-actions.css"

  Scenario: A site opts in to the icon display with post and share actions
    Given the page actions use the icon display with "x, reddit, share"
    When the agent-readable site is projected
    Then the agent page "hello/index.html" says "markus-page-actions-icons"
    And the agent page "hello/index.html" says "aria-label="View as Markdown""
    And the agent page "hello/index.html" says "aria-label="Copy Markdown""
    And the agent page "hello/index.html" says "aria-label="Post on X""
    And the agent page "hello/index.html" says "aria-label="Post on Reddit""
    And the agent page "hello/index.html" says "data-share"
    And the agent page "hello/index.html" says "data-icon="file-text""
    And the agent page "hello/index.html" says "data-icon="copy""

  Scenario: The post links work without JavaScript and carry only the title and the address
    Given the page actions use the icon display with "x, reddit"
    When the agent-readable site is projected
    Then the agent page "hello/index.html" says "https://x.com/intent/post?text=Hello&amp;url=https%3A%2F%2Fexample.org%2Fhello%2F"
    And the agent page "hello/index.html" says "https://www.reddit.com/submit?url=https%3A%2F%2Fexample.org%2Fhello%2F&amp;title=Hello"
    And the agent page "hello/index.html" says "target="_blank" rel="noopener noreferrer""
    And the agent page "hello/index.html" does not say "must%20never%20appear"
    And the agent page "hello/index.html" does not say "data-share"

  Scenario: The share popup is added by the script, so a page without JavaScript has no dead button
    Given the page actions use the icon display with "share"
    When the agent-readable site is projected
    Then the agent page "hello/index.html" says "data-share"
    And the agent page "hello/index.html" does not say "aria-haspopup"
    And the agent page "_plugins/papyrus-page-actions-v1.js" says "Share the web page"
    And the agent page "_plugins/papyrus-page-actions-v1.js" says "Share the Markdown"
    And the agent page "_plugins/papyrus-page-actions-v1.js" says "aria-haspopup"

  Scenario: A site with its own article template places the actions with one call
    Given the page actions use the icon display with "x, reddit, share"
    And the site has its own article template that places the page actions with article_actions
    When the agent-readable site is projected
    Then the agent page "hello/index.html" says "<article id="own"><div class="markus-page-actions markus-page-actions-header markus-page-actions-icons""
    And the agent page "hello/index.html" says "papyrus-page-actions-v1.js"

  Scenario: A site that does not link the component stylesheet gets a small one for the icon actions
    Given the page actions use the icon display with "x, reddit, share"
    And the site has its own article template that places the page actions with article_actions
    And the site does not link the component stylesheet
    When the agent-readable site is projected
    Then the agent site has these pages: "_plugins/papyrus-page-actions.css"
    And the agent page "hello/index.html" says "_plugins/papyrus-page-actions.css"
    And the agent page "_plugins/papyrus-page-actions.css" says ".markus-page-actions-icons"
    And the agent page "hello/index.html" does not say "markus-components.css"
