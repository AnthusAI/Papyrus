@backend @page-actions
Feature: Page actions on every page of a site that asks for them
  A reader who finds a good page wants to read it as Markdown, copy it, post it or share it, whether the page is an
  article or the home page, a listing, a section or collection front, a tag page, a page two of any of them, or a
  page an editor wrote as a file. The shared page actions already do this on article pages. A site opts in to the
  rest with one setting, pageActions.everywhere. Each page then offers its own title, its own canonical address and
  its own Markdown twin, and only a page that has a twin gets the actions, because the actions point at the twin.
  A site that does not opt in projects exactly the bytes it projected before.

  Background:
    Given a sectioned example site with the icon page actions and a collection "River writing" of everything tagged "Rivers"

  Scenario: A site that does not opt in keeps actions on articles only
    When the example site is projected
    Then the page "essays/fords/index.html" carries the page actions pointing at "/essays/fords/index.md"
    And the page "index.html" carries no page actions
    And the page "essays/index.html" carries no page actions
    And the page "tags/rivers/index.html" carries no page actions
    And the page "about/index.html" carries no page actions

  Scenario Outline: A site that opts in gets each page's own title, address and Markdown twin
    Given the site opts in to page actions on every page
    When the example site is projected
    Then the page "<page>" carries the page actions for "<twin>" titled "<title>" at "<address>"
    And the Markdown twin "<twin>" exists
    And the page "<page>" loads the page actions script

    Examples:
      | page                     | twin                      | title             | address                                   |
      | index.html               | /index.md                 | Example Ledger    | https://ledger.example.org/               |
      | essays/index.html        | /essays/index.md          | Essays            | https://ledger.example.org/essays/        |
      | essays/page/2/index.html | /essays/page/2/index.md   | Essays — page 2   | https://ledger.example.org/essays/page/2/ |
      | rivers/index.html        | /rivers/index.md          | River writing     | https://ledger.example.org/rivers/        |
      | tags/index.html          | /tags/index.md            | Tags              | https://ledger.example.org/tags/          |
      | tags/rivers/index.html   | /tags/rivers/index.md     | Tagged Rivers     | https://ledger.example.org/tags/rivers/   |
      | about/index.html         | /about/index.md           | About the Ledger  | https://ledger.example.org/about/         |

  Scenario: A page an editor wrote as a file carries its actions once, whether or not the site opts in
    Given the site has a page file "pages/models.md" at "topics/models" titled "Decision models"
    When the example site is projected
    Then the page "topics/models/index.html" carries the page actions for "/topics/models/index.md" titled "Decision models" at "https://ledger.example.org/topics/models/"
    Given the site opts in to page actions on every page
    When the example site is projected
    Then the page "topics/models/index.html" carries the page actions for "/topics/models/index.md" titled "Decision models" at "https://ledger.example.org/topics/models/"

  Scenario: The actions come first on a listing, or after it when the site puts them in the aside
    Given the site opts in to page actions on every page
    When the example site is projected
    Then on the page "essays/index.html" the page actions come before the heading
    Given the page actions go in the aside
    When the example site is projected
    Then on the page "essays/index.html" the page actions come after the cards

  Scenario: A page without a Markdown twin gets no actions
    Given the site opts in to page actions on every page
    And the site publishes no Markdown twins
    When the example site is projected
    Then no page carries page actions

  Scenario: A page that asks not to be indexed gets no actions
    Given the site opts in to page actions on every page
    And the example page "colophon" is noindex
    When the example site is projected
    Then the page "colophon/index.html" carries no page actions

  Scenario: A site with its own template places the actions once, where it wants them
    Given the site opts in to page actions on every page
    And the site has its own template that places the page actions on every page but articles
    When the example site is projected
    Then the page "index.html" carries the page actions once inside "own"
    And the page "essays/index.html" carries the page actions once inside "own"
    And the page "tags/rivers/index.html" carries the page actions once inside "own"

  Scenario: Without the setting a site's own template gets nothing from the call
    Given the site has its own template that places the page actions on every page but articles
    When the example site is projected
    Then the page "essays/index.html" carries no page actions
