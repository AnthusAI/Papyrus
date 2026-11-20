Feature: A repair that is right is not thrown back for the advice it brings
  The run polishes a translation block by block and keeps a repair only when it does not make faithfulness worse. A repair that renders a capitalized name the target
  language's way (the U.S. Army is "el Ejército de EE. UU.") makes the names check advise that the name is not written as in the source, which is a note for the glossary and
  the judge and not a loss. Such a note alone never throws a repair back; an error, or any other new warning, still does. A translation held for a glossary term that its repair
  would have fixed therefore reaches a person's review only when the text is really wrong.

  Scenario: A repair that only adds the advice about a locally written name is kept
    Given a block with the error "glossary" and no other finding
    When the repair has only the warning "names-adapted"
    Then the repair is not worse

  Scenario: A repair that adds any other warning, or an error, is thrown back
    Given a block with the error "glossary" and no other finding
    When the repair has the warning "hedges"
    Then the repair is worse
