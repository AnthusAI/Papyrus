Feature: A Markdown twin is shown in the browser, and still served as Markdown to a client that asks for it
  Every site publishes a Markdown twin of its pages (/x/index.md) and stores it as text/markdown. Safari downloads that
  type, so the "View as Markdown" link and a shared link to a twin saved a file instead of showing the text. The edge
  answers a browser with the same bytes as text/plain; charset=utf-8, which every browser displays. A client whose Accept
  header prefers text/markdown (an agent, a script) and a client that names no type still get text/markdown. The edge
  changes what one viewer is sent, never the stored object or its cache entry, so one kind of client cannot make the
  other see its response. The twin carries no attachment header.
  These scenarios run the viewer-response function against synthetic requests: scripts/test-markdown-content-type-function.mjs
  (npm run test:markdown-twin-display), which also runs in the full node test suite.

  Background:
    Given a Markdown twin stored as "text/markdown; charset=utf-8"

  Scenario: Safari following the View as Markdown link is shown the text
    When a viewer asks for the twin with the Accept header "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    Then the twin is sent as "text/plain; charset=utf-8"
    And the twin is sent without an attachment header

  Scenario: Any browser that lists text/html is shown the text
    When a viewer asks for the twin with the Accept header "text/html"
    Then the twin is sent as "text/plain; charset=utf-8"

  Scenario: A client that prefers text/markdown still gets text/markdown
    When a viewer asks for the twin with the Accept header "text/markdown, text/html;q=0.5"
    Then the twin is sent as "text/markdown; charset=utf-8"

  Scenario: A client that names no type still gets text/markdown
    When a viewer asks for the twin with the Accept header "*/*"
    Then the twin is sent as "text/markdown; charset=utf-8"

  Scenario: A client that sends no Accept header still gets text/markdown
    When a viewer asks for the twin with no Accept header
    Then the twin is sent as "text/markdown; charset=utf-8"

  Scenario: The two kinds of client share one cached object and the response says what it varies on
    When a viewer asks for the twin with the Accept header "text/html"
    And a viewer asks for the twin with the Accept header "text/markdown"
    Then both responses say they vary on "Accept"

  Scenario: A page that is not a twin is not touched
    Given a page stored as "text/html; charset=utf-8"
    When a viewer asks for the twin with the Accept header "text/html"
    Then the twin is sent as "text/html; charset=utf-8"
