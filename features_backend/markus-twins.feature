Feature: Agent twins carry Markus source
  The Markdown twin of a page is Markus source, not plain Markdown: directives stay as written (an image
  with all its attributes, the page blocks), and an island carries a text fallback, in the page for
  readers without JavaScript and in the twin. The file extension and the text/markdown type are unchanged.

  Background:
    Given an agent-readable site with an article "hello" and the page file "pages/models.md" at "topics/models" titled "Decision models" described as "How decisions get made."
    And the page file "pages/models.md" is
      """
      ::band{id="top" tone="card"}
      # Decision models

      A model *decides*.

      ::button{href="/start/" label="Start" size="lg"}
      ::button{href="https://example.org/" label="Source" variant="secondary"}

      ::column{panel="card"}
      ::island{name="Chart" height="20rem" kind="bar" summary="A bar chart of accuracy by model: 2B leads."}
      """

  Scenario: The twin of a page keeps its page blocks as written
    When the agent-readable site is projected
    Then the agent page "topics/models/index.md" says "::band{id="top" tone="card"}"
    And the agent page "topics/models/index.md" says "::column{panel="card"}"
    And the agent page "topics/models/index.md" says "::button{href="/start/" label="Start" size="lg"}"
    And the agent page "topics/models/index.md" says "::button{href="https://example.org/" label="Source" variant="secondary"}"

  Scenario: An island carries its summary in the page and in the twin
    When the agent-readable site is projected
    Then the agent page "topics/models/index.html" says "<p class="papyrus-island-summary">A bar chart of accuracy by model: 2B leads.</p></div>"
    And the agent page "topics/models/index.html" does not say "data-props='{"kind":"bar","summary""
    And the agent page "topics/models/index.md" says "summary="A bar chart of accuracy by model: 2B leads.""
    And the agent page "llms-full.txt" says "A bar chart of accuracy by model: 2B leads."

  Scenario: An article twin keeps its image directive with every attribute
    The image pipeline needs renditions, which this fixture does not have, so the twin is built from the source text.

    When the twin of an article is built from this source
      """
      ---
      title: Wide
      ---
      Words.

      ::image{src="images/wide.png" alt="A wide chart" layout="full" caption="Wide"}
      """
    Then the twin text says "::image{src="images/wide.png" alt="A wide chart" layout="full" caption="Wide"}"
    And the twin text does not say "![A wide chart]"
    And the twin text does not say "title: Wide"
