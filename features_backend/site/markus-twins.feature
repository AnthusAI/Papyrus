Feature: Agent twins carry Markus source
  The Markdown twin of an article is Markus source, not plain Markdown: directives stay as written, an image
  with all its attributes. The page blocks of an authored page (band, column, button, island, include) are a
  template for the HTML page and not content, so the twin of an authored page says what they show (see
  page-twins.feature): a button is a link and an island is its text summary, which is also in the page for
  readers without JavaScript. The file extension and the text/markdown type are unchanged.

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

  Scenario: The twin of a page says what its page blocks show and keeps none of them
    When the agent-readable site is projected
    Then the agent page "topics/models/index.md" says "# Decision models"
    And the agent page "topics/models/index.md" says "A model *decides*."
    And the agent page "topics/models/index.md" says "[Start](https://example.org/start/)"
    And the agent page "topics/models/index.md" says "[Source](https://example.org/)"
    And the agent page "topics/models/index.md" does not say "::band"
    And the agent page "topics/models/index.md" does not say "::column"
    And the agent page "topics/models/index.md" does not say "::button"

  Scenario: An island carries its summary in the page and in the twin
    When the agent-readable site is projected
    Then the agent page "topics/models/index.html" says "<p class="papyrus-island-summary">A bar chart of accuracy by model: 2B leads.</p></div>"
    And the agent page "topics/models/index.html" does not say "data-props='{"kind":"bar","summary""
    And the agent page "topics/models/index.md" says "A bar chart of accuracy by model: 2B leads."
    And the agent page "topics/models/index.md" does not say "::island"
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
