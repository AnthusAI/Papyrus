Feature: Equations in Stories
  An author writes an equation as TeX. A display equation is a fenced block whose info string is "math"; an inline
  equation is a code span with a dollar sign on each side. The code span keeps Markdown from reading the underscores,
  asterisks, backslashes and braces in TeX. A bare dollar sign is never math, because stored articles contain prices.

  The projected page carries MathML generated while the page is built: no script, no web font, and the text takes the
  page's colour, so both themes work. The TeX stays the source of truth: the Markdown twin and llms-full.txt keep it
  verbatim, and an email shows it as code because mail clients ignore MathML. TeX that cannot be converted never breaks a
  page and never loses text: the author's source is shown as code, and saving the Story warns.

  Background:
    Given a standard site with an article "bound"

  Scenario: A display equation becomes MathML
    Given the article "bound" has the body
      """
      The attacker's chance is bounded.

      ```math
      \Pr[\text{guess}] \le m / 2^k
      ```
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" says "<div class="papyrus-math"><math xmlns="http://www.w3.org/1998/Math/MathML" display="block""
    And the agent page "bound/index.html" says "<mtext>guess</mtext>"
    And the agent page "bound/index.html" says "<msup><mn>2</mn><mi>k</mi></msup>"
    And the agent page "bound/index.html" does not say "language-math"
    And the agent page "bound/index.html" does not say "mathjax"
    And the agent page "bound/index.html" does not say "katex"

  Scenario: An inline equation becomes inline MathML in the sentence
    Given the article "bound" has the body
      """
      With a key of $`k`$ bits the chance is at most $`m / 2^k`$ per try.
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" says "display="inline""
    And the agent page "bound/index.html" does not say "<code>"
    And the agent page "bound/index.html" does not say "$"

  Scenario: TeX punctuation inside an inline equation is not read as Markdown
    Given the article "bound" has the body
      """
      Each $`a_i * b_j \{0,1\}^n`$ term and *this* is emphasis.
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" says "<msub><mi>a</mi><mi>i</mi></msub>"
    And the agent page "bound/index.html" says "<em>this</em>"

  Scenario: Dollar prices are not equations
    Given the article "bound" has the body
      """
      It costs $5 to start, or $6 a month, not $10 `flat` $20.
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" says "$5 to start, or $6 a month, not $10 <code>flat</code> $20."
    And the agent page "bound/index.html" does not say "<math"

  Scenario: A multi-line aligned equation is a table of rows
    Given the article "bound" has the body
      """
      ```math
      \begin{aligned} a &= b + c \\ d &= e \end{aligned}
      ```
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" says "<mtable"
    And the agent page "bound/index.html" does not say "(1)"

  Scenario: Named operators are spaced like words, not like equals signs
    Given the article "bound" has the body
      """
      ```math
      \Pr[X = x] \le m / 2^k
      ```
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" says "<mo movablelimits="true" lspace="0em" rspace="0.1667em">Pr</mo>"

  Scenario: An operator under a script carries no spacing of its own, so WebKit does not loosen the subscript
    Given the article "bound" has the body
      """
      ```math
      H_\infty(X) = \max_x \Pr[X = x]
      ```
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" says "<msub><mi>H</mi><mo lspace="0em" rspace="0em">∞</mo></msub>"
    And the agent page "bound/index.html" says "<msub><mo lspace="0em" rspace="0em">max</mo><mi>x</mi></msub><mspace width="0.1667em"></mspace>"

  Scenario: Equations ask for a system math font, because the generic one can lack the math table
    Given the article "bound" has the body
      """
      ```math
      \sum_{i=1}^{n} x_i
      ```
      """
    When the agent-readable site is projected
    Then the agent page "css/markus-components.css" says "font-family: "STIX Two Math", "Cambria Math""
    And the agent page "css/markus-components.css" does not say "@font-face"

  Scenario: The Markdown twin and llms-full.txt keep the TeX source
    Given the article "bound" has the body
      """
      Chance $`m / 2^k`$.

      ```math
      \sum_{i=1}^{n} x_i
      ```
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.md" says "$`m / 2^k`$"
    And the agent page "bound/index.md" says "\sum_{i=1}^{n} x_i"
    And the agent page "bound/index.md" does not say "<math"
    And the agent page "llms-full.txt" says "\sum_{i=1}^{n} x_i"

  Scenario: TeX that cannot be converted is shown as code, not lost
    Given the article "bound" has the body
      """
      Before.

      ```math
      \frac{ a_{
      ```

      After.
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" says "<pre><code class="language-math">\frac{ a_{"
    And the agent page "bound/index.html" says "Before."
    And the agent page "bound/index.html" says "After."
    And the agent page "bound/index.html" does not say "<math"

  Scenario: Markup typed inside TeX is escaped, never injected
    Given the article "bound" has the body
      """
      ```math
      \text{</mtext><script>alert(1)</script><mtext>}
      ```

      Inline $`\text{<img src=x onerror=alert(2)>}`$ and $`\href{javascript:alert(3)}{x}`$.
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" does not say "<script>alert(1)"
    And the agent page "bound/index.html" does not say "<img src=x"
    And the agent page "bound/index.html" does not say "href="javascript"
    And the agent page "bound/index.html" says "&lt;script&gt;alert(1)"

  Scenario: A page without equations is unchanged
    Given the article "bound" has the body
      """
      Plain text with `code` and a price of $5.
      """
    When the agent-readable site is projected
    Then the agent page "bound/index.html" does not say "papyrus-math"
    And the agent page "bound/index.html" does not say "<math"

  Scenario: Saving a Story with good equations raises no warning
    When I derive the body of an article containing
      """
      Chance $`m / 2^k`$.

      ```math
      H_\infty(X) = -\log_2 \max_x \Pr[X = x]
      ```
      """
    Then the derivation is ok
    And the derivation has no warnings

  Scenario: Saving a Story with TeX that will not convert warns and still saves
    When I derive the body of an article containing
      """
      Intro.

      ```math
      \frac{
      ```
      """
    Then the derivation is ok
    And the derivation warns with code "equation-tex" on line 3
    And the stored body keeps the TeX source "\frac{"

  Scenario: An email shows the TeX source in code styling
    When I render an email whose body is
      """
      Chance $`m / 2^k`$.

      ```math
      \frac{a}{b}
      ```
      """
    Then the email html does not say "<math"
    And the email html says "m / 2^k"
    And the email html says "\frac{a}{b}"
    And the email text says "m / 2^k"
    And the email text says "\frac{a}{b}"
