Feature: Authored pages and Markus twins are agent-readable
  A page written as a file (a "pages" entry with a source) is read by agents the way an article is: its
  Markdown twin is listed in llms.txt and carried by llms-full.txt, the page has the page actions and the
  head link to the twin. A noindex page has none of these.

  Background:
    Given an agent-readable site with an article "hello" and the page file "pages/models.md" at "topics/models" titled "Decision models" described as "How decisions get made."
    And the page file "pages/models.md" is
      """
      ::band{id="top" tone="card"}
      # Decision models

      A model *decides*.

      ::button{href="/start/" label="Start" size="lg"}
      ::button{href="https://example.org/" label="Source" variant="secondary"}
      """

  Scenario: An authored page is listed in llms.txt and llms-full.txt and has page actions
    When the agent-readable site is projected
    Then the agent page "llms.txt" says "[Decision models](https://example.org/topics/models/index.md): How decisions get made."
    And the agent page "llms.txt" says "[Hello](https://example.org/hello/index.md)"
    And the agent page "llms-full.txt" says "A model *decides*."
    And the agent page "topics/models/index.html" says "data-markdown="/topics/models/index.md""
    And the agent page "topics/models/index.html" says "Copy Markdown"
    And the agent page "topics/models/index.html" says "View as Markdown"
    And the agent page "topics/models/index.html" says "Open in ChatGPT"
    And the agent page "topics/models/index.html" says "Open in Claude"
    And the agent page "topics/models/index.html" says "Open in Perplexity"
    And the agent page "topics/models/index.html" says "<link rel="alternate" type="text/markdown" href="/topics/models/index.md">"

  Scenario: An authored page under a base path is listed in llms.txt with prefixed links
    Given the agent-readable site lives under the base path "/posts"
    When the agent-readable site is projected
    Then the agent page "posts/llms.txt" says "[Decision models](https://example.org/posts/topics/models/index.md): How decisions get made."
    And the agent page "posts/llms-full.txt" says "A model *decides*."
    And the agent page "posts/topics/models/index.html" says "data-markdown="/posts/topics/models/index.md""

  Scenario: A noindex authored page has no twin, no llms entry and no page actions
    Given the page "topics/models" is noindex
    When the agent-readable site is projected
    Then the agent site lacks these pages: "topics/models/index.md"
    And the agent page "llms.txt" does not say "Decision models"
    And the agent page "llms-full.txt" does not say "A model *decides*."
    And the agent page "topics/models/index.html" does not say "data-papyrus-page-actions"
