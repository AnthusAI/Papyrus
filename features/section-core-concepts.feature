Feature: Editors choose the core concepts of a section, from the section's settings and from a concept's own page
  A core concept is a concept every agent working in a section is told about, with the editor's note on why the section cares. In the
  section's settings, directly under the section's mission and policy, a "Core concepts" area has the same typed # box as the Related
  section on a Reference, with a "Create #name" action that really makes the concept on a site, and a row for each concept with its
  note and a Remove button. Words are plain: the word is "core concept", the sentence says every agent in the section is told about it.
  On a concept's page, "Core concept of" lists only the sections that have it, each with a Remove control, and one "Add to a section"
  button reveals a button for each other section, such as "Add to Security". Making a concept without tagging a Reference is a backend
  mutation open to editors and admins only, and it makes the same concept the hashtag box and the command line make. The pages use flat
  colours and rounded rectangles.

  Scenario: The stored list is read once for each concept and edited one concept at a time
    Given the stored core concepts of a section
    When an editor adds, notes and removes core concepts
    Then each concept is held once, in the order added, and an empty note is none

  Scenario: Section settings show the core concepts with a note and a Remove button for each
    Given the stored core concepts of a section
    When the section's settings are drawn
    Then the heading says "Core concepts" and the help sentence is kept
    And each concept has its note box and a Remove button
    And the word "track" appears nowhere

  Scenario: A concept's page lists the sections that have it and offers one button to add it to another
    Given the stored core concepts of a section
    When a concept's page is drawn
    Then "Core concept of" lists only the sections that have the concept, each with a Remove control
    And one "Add to a section" button is shown and no section button is shown yet

  Scenario: An editor can make a concept without tagging a Reference
    Given the schema files and the backend handler
    When the backend mutation is read
    Then createEditorConcept takes a name, is open to editors and admins only, and is routed to the concept writer
