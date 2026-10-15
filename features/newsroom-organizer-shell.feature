Feature: Production newsroom organizer shell
  The approved newsroom appearance preserves the existing authenticated CMS.

  Scenario: The complete CMS survives a navigation change
    Given an editor has an authorized session and existing newsroom records
    When the publication enables the organizer newsroom layout
    Then taxonomy, concepts, knowledge search, reference curation and policies remain reachable
    And sections, procedures, messages, assignments and article editing retain their original commands
    And administrator identity merging retains its original authorization
    And Settings retains theme, motion and interface preferences
    And unsupported semantic graph merging is not reported as completed

  Scenario: Taxonomy retains its own editor
    Given the organizer newsroom layout is enabled
    When an editor opens Taxonomy or a saved taxonomy category link
    Then the original taxonomy editor opens with its save and doctrine handlers
    And Topic proposals remains a separate destination
    And other publications retain their existing route aliases

  Scenario: Board projects native records without changing their workflow
    Given an editor is authorized to read CMS records
    When the editor opens Board
    Then native articles, current references and assignments retain their IDs and statuses
    And source links open the canonical reference lineage in the existing curator
    And unknown assignment statuses remain visible
    And mutation actions remain in their original authorized workspaces
    And a signed-out or forbidden session loads no board records

  Scenario: Complete navigation is consistent on desktop and mobile
    Given a publication has enabled the organizer newsroom layout
    When an editor opens a newsroom destination
    Then desktop navigation and the mobile menu show the same grouped destinations and descriptions
    And Overview, Board and Articles are the leading destinations
    And bottom tabs show icons and labels without descriptions

  Scenario: Collapsing desktop navigation returns space to the workspace
    Given the organizer sidebar is expanded
    When I activate Collapse sidebar with the keyboard
    Then the workspace grows and Expand sidebar remains reachable
    And my preference survives navigation and reload

  Scenario: The account menu uses the actual authenticated session
    Given an editor is signed in
    When I open Account menu
    Then I see the real session identity and working Settings and sign-out controls
    And the account control remains visible on narrow screens

  Scenario: A signed-out visitor cannot read private newsroom data
    Given there is no authenticated editor session
    When I open a private newsroom destination
    Then the existing access gate remains in place
    And the organizer shell grants no new role or data access

  Scenario: Unconfigured integrations remain unavailable
    Given production classifier execution is not configured
    When I inspect the newsroom controls
    Then no synthetic prediction or local service is presented as a live integration

  Scenario: Existing publication chrome remains unchanged until opted in
    Given a publication has not enabled the organizer newsroom layout
    When I open the newsroom
    Then its existing CMS shell and commands remain unchanged

  Scenario: Settings works on a CMS hosted at the root
    Given the publication hosts its newsroom at the root path
    When I open Settings from the account menu
    Then the existing Settings page opens through the newsroom route alias
    And its cloud authorization and preference handlers are unchanged
