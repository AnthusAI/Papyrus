Feature: A cited Story never links to a source list that is not on the page, and a site chooses how sources are linked
  A Story cites a source with a [@key] marker, and the page numbers each marker and lists the sources in a bibliography.
  A body that has markers but no ::citations{} line used to number its markers as links to a list that was never
  printed, so every number led nowhere. Now the page adds the bibliography at the end of the article whenever a body
  has markers and no ::citations{} line, so a marker always points at an entry that is on the page. The Story's
  checklist says the same thing earlier, in plain words and with the markers named: before publishing, the citation
  check tells the editor which markers have no ::citations{} line and which markers name a source the Story does not
  list. These are advice (the check's default severity is a warning, to be mentioned in the review step's note); a
  marker with an unknown key is also refused outright when the Story is saved.

  A site also chooses how its bibliography links a source, in web/projection.json: "citations": {"links": "external"},
  "internal" or "none". With external, which is what every site did before and what a site gets when it says nothing,
  each source links to its own address. With internal, no entry links to an address outside the site: a source is
  linked only to the site's own page for it when the Story's entry names one (a path on this site), and otherwise
  shows as plain text. With none, every entry is plain text: the title, the publisher and the date. Machines on
  Machines uses internal, so nothing in its bibliography or its citation markers leaves the site.

  Scenario: A body with markers and no bibliography line gets the bibliography instead of dead links
    Given a Papyrus site whose citations setting is not declared
    When the site renders a Story with citation markers and no bibliography line
    Then every citation number links to an entry on the same page
    And the page lists "A Page Cited" once, inside the article

  Scenario: A body that already says where the bibliography goes is left as written
    Given a Papyrus site whose citations setting is not declared
    When the site renders a Story with citation markers and a bibliography line
    Then every citation number links to an entry on the same page
    And the page lists "A Page Cited" once, inside the article

  Scenario: A site that says nothing links a source out, unless the site has a page for it
    Given a Papyrus site whose citations setting is not declared
    When the site renders a Story with citation markers and a bibliography line
    Then the source "Another Page" links to "https://example.net/other"
    And the source "A Page Cited" links to "/references/smith/"
    And the page is the same as for a site whose citations links are "external"

  Scenario: A site that says nothing keeps the original outside link, with no icon
    Given a Papyrus site whose citations setting is not declared
    When the site renders a Story with citation markers and a bibliography line
    Then the source "Another Page" has no icon and opens in a new tab

  Scenario: A source that leaves the site opens in a new tab and carries the external-link icon when the site opts in
    Given a Papyrus site whose citations setting is externalIcon

    When the site renders a Story with citation markers and a bibliography line
    Then the source "Another Page" opens in a new tab and carries the external-link icon

  Scenario: A source that stays on the site carries no icon and opens in the same tab
    Given a Papyrus site whose citations setting is externalIcon
    When the site renders a Story with citation markers and a bibliography line
    Then the source "A Page Cited" has no icon and does not open a new tab

  Scenario: A source with both a DOI and a URL keeps them apart
    Given a Papyrus site whose citations setting is not declared
    When the site renders a Story citing a paper that has both a DOI and a URL
    Then the bibliography entry ends with the DOI, a space, and the link to the URL

  Scenario: A source with only a DOI ends with the DOI
    Given a Papyrus site whose citations setting is not declared
    When the site renders a Story citing a paper that has only a DOI
    Then the bibliography entry shows the DOI and no link

  Scenario: A source with only a URL links it after a space
    Given a Papyrus site whose citations setting is not declared
    When the site renders a Story citing a paper that has only a URL
    Then the bibliography entry shows the link to the URL after a space and no DOI

  Scenario Outline: A site that links no outside address has none in its bibliography
    Given a Papyrus site whose citations links are "<mode>"
    When the site renders a Story with <bibliography>
    Then the page has no link to an outside address
    And the page shows the title, publisher and date of "A Page Cited" as text

    Examples:
      | mode     | bibliography                                     |
      | internal | citation markers and a bibliography line         |
      | internal | citation markers and no bibliography line        |
      | none     | citation markers and a bibliography line         |
      | none     | citation markers and no bibliography line        |

  Scenario: Internal links a source only to the site's own page for it
    Given a Papyrus site whose citations links are "internal"
    When the site renders a Story with citation markers and a bibliography line
    Then the source "A Page Cited" links to "/references/smith/"
    And the source "Another Page" is plain text

  Scenario: A site refuses a citations setting it does not understand
    Then the setting {"links": "sideways"} is refused with a message naming "citations.links"

  Scenario: The checklist's citation check names the markers that have no bibliography line
    Given a Story with the front matter
      """
      title: Board refuses
      citations:
        minutes:
          type: webpage
          title: Minutes
      """
    And the Story body
      """
      The board met [@minutes].
      """
    When the lens checks run
    Then the finding "A5" is a "concern"
    And the finding "A5" says "[@minutes]"
    And the finding "A5" says "no ::citations{} line"

  Scenario: The checklist's citation check names a marker whose key is not among the Story's entries
    Given a Story with the front matter
      """
      title: Board refuses
      citations:
        minutes:
          type: webpage
          title: Minutes
      """
    And the Story body
      """
      The board met [@minutes] and left [@ghost].

      ::citations
      """
    When the lens checks run
    Then the finding "A5" is a "concern"
    And the finding "A5" says "[@ghost]"
