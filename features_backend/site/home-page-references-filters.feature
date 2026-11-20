@backend @home-page-references-filters
Feature: A references include can say none of, and several sections, and the filters apply to paged lists
  A site can list the References that belong to no section of its own, or the ones that are not videos, without deleting tiles from a hook after the
  engine drew them. The references include takes section="A|B" (any of several sections), notSection="A|B" (none of these sections) and
  notMedium="video" (not this medium). They narrow the candidates before the count, the page ledger and the paging, so a paged list is cut from the
  filtered References and no data file of it is empty, and the Markdown twin lists exactly what the page lists. A Reference with no section passes
  notSection, a Reference filed under a section that is not listed passes it too, and a Reference with no medium passes notMedium. Nothing is read
  from the backend: the snapshot already carries section and medium. A page that uses none of the new attributes is drawn exactly as before.

  Scenario: A paged list of References with no section of the site's
    Given a snapshot of 200 accepted References, 150 filed under "Agents" or "Science", 50 with no section and 5 filed under "Papyrus"
    And a page with a paged references include with notSection "Agents|Science", a first page of 24 and the id "unheaded"
    When the filtered references site is projected
    Then the page and the data files of the "unheaded" list together hold exactly the 55 References not filed under Agents or Science, each once
    And no data file of the "unheaded" list is empty

  Scenario: Findings that are not videos
    Given a snapshot of accepted videos and accepted articles
    And a page with a references include with notMedium "video" and a count of 6
    When the filtered references site is projected
    Then no card on the page is a video and the page shows 6 cards

  Scenario: Several sections
    Given a snapshot of accepted References in "Agents", "Science" and "Art"
    And a page with a references include with section "Agents|Science" and a count of 50
    When the filtered references site is projected
    Then the page shows the Agents and Science References and no Art Reference

  Scenario: The Markdown twin lists what the page lists
    Given a snapshot of accepted References in "Agents", "Science" and "Art"
    And a page with a references include with section "Agents|Science" and a count of 50
    When the filtered references site is projected
    Then the Markdown twin of the page lists the same References as the page

  Scenario: medium and notMedium together is a build error that names the page
    Given a snapshot of accepted videos and accepted articles
    And a page with a references include with medium "video" and notMedium "video"
    Then projecting the site stops and the error names the page and says medium and notMedium cannot be used together

  Scenario: notMedium with an unknown medium is a build error that names the page
    Given a snapshot of accepted videos and accepted articles
    And a page with a references include with notMedium "podcast"
    Then projecting the site stops and the error names the page and the allowed media

  Scenario: A page with none of the new attributes is drawn as before
    Given a snapshot of accepted References in "Agents", "Science" and "Art"
    And a page with a paged references include with section "Art" and no id
    When the filtered references site is projected
    Then the list is named "recent-art" and shows only the Art References
