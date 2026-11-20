@backend @reference-page-titles
Feature: A Reference is titled with its page's real title, never with its own web address
  A web search that cites a page without naming it hands the monitor a result titled with the address, and the new Reference kept that address as
  its title even though the page's real title was read a moment later for the link preview and for capture. Now the page's own title replaces the
  address once, when the Reference is created or captured, and only while the title still is an address: a title an editor chose, or one the source
  gave, is never replaced, and neither is a title that was set in the meantime. A bot wall's or error page's stock title ("Just a moment...") is not
  a page title. A change to the title reaches the public page like any other change to a card. A Reference that already exists is repaired once by
  "papyrus references repair-titles", signed in as an editor with no AWS credentials. It previews by default and reads only the site's own records:
  it says how many References already hold the page's title (in the stored link preview or the capture card) and can be repaired without fetching
  anything, and how many need their page read again, which only "--fetch" does. A page that cannot be read leaves the Reference as it is, and its card
  shows a readable name made from the site and the words of the address, never the raw address and never presented as a real title. Nothing here
  touches production, the network or a model: the site and the pages are in memory.

  Background:
    Given a site with References titled with their own address, one with a stored page title, one with only a capture card, one with nothing stored, and one titled by an editor

  Scenario: A new Reference takes the title its page declared
    When a new Reference titled with its address gets its link preview from a page titled "AI Coding Assistants as Attack Surface"
    Then the new Reference is titled "AI Coding Assistants as Attack Surface"

  Scenario: A title an editor chose is never replaced
    When a new Reference titled "The editor's title" gets its link preview from a page titled "AI Coding Assistants as Attack Surface"
    Then the new Reference is titled "The editor's title"

  Scenario: A bot wall's title is not taken for the page's title
    When a new Reference titled with its address gets its link preview from a page titled "Just a moment..."
    Then the new Reference is titled with its address

  Scenario: The repair previews by default and says what needs no fetch
    When the title repair runs
    Then no title was written and no page was read
    And the repair counted 2 fixable from stored titles and 1 that would need a fetch

  Scenario: The repair records the stored titles and leaves the others alone
    When the title repair runs with write
    Then the Reference with a stored page title is titled "From the preview"
    And the Reference with a capture card is titled "From the capture card"
    And the Reference with nothing stored is still titled with its address
    And the Reference titled by an editor is untouched

  Scenario: Reading the other pages needs an explicit request
    When the title repair runs with write and fetch and the page is titled "Fetched title"
    Then the Reference with nothing stored is titled "Fetched title"
    And only the Reference with nothing stored had its page read

  Scenario: A page that cannot be read is said so and shows a readable name
    When the title repair runs with write and fetch and the page is blocked
    Then the Reference with nothing stored is still titled with its address
    And the repair said the page was not readable and what the card shows instead

  Scenario: A card never shows a raw address
    Given the preview of the Reference with nothing stored names the site "Lab Space"
    When the public card of the Reference with nothing stored is built
    Then the card title is a readable name starting with "Lab Space:"
    And the card title is not a web address

  Scenario: A repaired title reaches the public page
    Then a title change on an accepted Reference rebuilds the public page

  Scenario: A title written before the first prediction needs no rebuild of its own
    Then a title change on a pending Reference nobody has predicted rebuilds nothing, because the first prediction is the change that shows it
