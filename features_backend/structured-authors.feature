Feature: Authors are names, however the front matter writes them
  An item lists its authors in front matter in one of three forms: a string ("Ann Lee, Bo Reed"), a list of
  strings, or a list of objects with a name and an optional url. One shared reading turns each form into
  authors, and every output that shows or serialises authors uses it. A reader or a feed
  aggregator sees the person's name, never the text of the object, and an author's url becomes a link where the
  format can carry one: an absolute uri in Atom, a Markdown link in the Markdown twin, a url on the JSON-LD
  person and a link in the HTML byline. The public data files list author names, and leave the key out for an
  item with no authors.

  Background:
    Given a site with articles by a string, by a list, by objects and by nobody has been projected

  Scenario: The Atom feed names each author and gives the url as an absolute uri
    Then the Atom entry "by-objects" has the authors "Ryan Porter, Derek Norrbom, Eve Stone"
    And the Atom author "Ryan Porter" has the uri "https://authors.example.org/ryan"
    And the Atom author "Derek Norrbom" has the uri "https://www.linkedin.com/in/dereknorrbom/"
    And the Atom author "Eve Stone" has no uri
    And the Atom entry "by-string" has the authors "Ann Lee, Bo Reed"
    And the Atom entry "by-list" has the authors "Cy Marsh, Di Wood"
    And the Atom entry "anonymous" has no authors
    And the page "atom.xml" does not say "{'name'"

  Scenario: The RSS feed names each author in dc:creator
    Then the RSS item "by-objects" has the creators "Ryan Porter, Derek Norrbom, Eve Stone"
    And the RSS item "by-string" has the creators "Ann Lee, Bo Reed"
    And the RSS item "anonymous" has no creators

  Scenario: The Markdown twin shows names and links the ones with a url
    Then the page "by-objects.md" says "By [Ryan Porter](https://authors.example.org/ryan), [Derek Norrbom](https://www.linkedin.com/in/dereknorrbom/), Eve Stone · Published 2026-03-03"
    And the page "by-list.md" says "By Cy Marsh, Di Wood · Published 2026-03-02"
    And the page "by-string.md" says "By Ann Lee, Bo Reed · Published 2026-03-01"
    And the page "by-objects.md" does not say "{'name'"

  Scenario: The structured data names each person and gives the url
    Then the page "by-objects.html" says ""name":"Ryan Porter","url":"https://authors.example.org/ryan""
    And the page "by-objects.html" does not say "{'name'"

  Scenario: The public data files list author names and omit the key when there are none
    Then the public data entry "/by-objects.html" has the authors "Ryan Porter, Derek Norrbom, Eve Stone"
    And the public data entry "/by-string.html" has the authors "Ann Lee, Bo Reed"
    And the public data entry "/by-list.html" has the authors "Cy Marsh, Di Wood"
    And the public data entry "/anonymous.html" has no authors key
