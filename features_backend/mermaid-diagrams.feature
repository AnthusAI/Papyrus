Feature: Mermaid diagrams render on every standard site
  An author writes a diagram as a fenced code block whose info string is "mermaid". The projected page draws it as
  a diagram in the browser, with the library served from the site's own origin and fetched only by pages that have a
  diagram. The source is always still there as text: in the page before the script runs (and without JavaScript), and
  verbatim in the page's Markdown twin, which agents read.

  Background:
    Given a standard site with an article "flow"

  Scenario: A page with a Mermaid block loads the renderer and shows the diagram container
    Given the article "flow" has the body
      """
      Before the diagram.

      ```mermaid
      flowchart TD
        A[Start] --> B[Done]
      ```
      """
    When the agent-readable site is projected
    Then the agent page "flow/index.html" says "<pre><code class="language-mermaid">flowchart TD"
    And the agent page "flow/index.html" says "src="/_plugins/papyrus-mermaid-v1.js?v="
    And the agent page "flow/index.html" says "data-library="/_plugins/mermaid-11.17.2.min.js""
    And the site publishes its own copy of the Mermaid library and loader

  Scenario: A page without a Mermaid block loads no Mermaid script
    Given the article "flow" has the body
      """
      A plain article with a code sample.

      ```python
      print("hello")
      ```
      """
    When the agent-readable site is projected
    Then the agent page "flow/index.html" does not say "mermaid"

  Scenario: The Markdown twin keeps the Mermaid source verbatim
    Given the article "flow" has the body
      """
      ```mermaid
      graph TD
        A["x < y & z"] --> B
      ```
      """
    When the agent-readable site is projected
    Then the agent page "flow/index.md" contains
      """
      ```mermaid
      graph TD
        A["x < y & z"] --> B
      ```
      """

  Scenario: With JavaScript off the source stays readable
    Given the article "flow" has the body
      """
      ```mermaid
      flowchart LR
        A --> B
      ```
      """
    When the agent-readable site is projected
    Then the agent page "flow/index.html" contains
      """
      <pre><code class="language-mermaid">flowchart LR
        A --&gt; B
      </code></pre>
      """

  Scenario: Diagram text containing HTML is escaped in the page, never injected
    Given the article "flow" has the body
      """
      ```mermaid
      flowchart TD
        A["<img src=x onerror=alert(1)>"] --> B["<script>alert(2)</script>"]
      ```
      """
    When the agent-readable site is projected
    Then the agent page "flow/index.html" says "&lt;img src=x onerror=alert(1)&gt;"
    And the agent page "flow/index.html" does not say "<img src=x"
    And the agent page "flow/index.html" does not say "<script>alert(2)"

  Scenario: A site can turn Mermaid off
    Given the site's projection settings say "mermaid" is {"enabled": false}
    And the article "flow" has the body
      """
      ```mermaid
      flowchart TD
        A --> B
      ```
      """
    When the agent-readable site is projected
    Then the agent page "flow/index.html" does not say "mermaid-v1"
    And the agent page "flow/index.html" says "language-mermaid"
    And the site does not publish the Mermaid library or loader
