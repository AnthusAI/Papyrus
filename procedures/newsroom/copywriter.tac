-- Papyrus automated newsroom copywriter procedure.
--
-- Dry-run first: copywriting Assignments consume selected private reporting
-- packets and produce reader-facing draft payloads. Reporting packets remain
-- private Message work products; the CLI/procedure layer owns deterministic
-- draft Item persistence and must never create EditionItem placement.

local done = require("tactus.tools.done")

Toolset "papyrus" {
    type = "plugin",
    paths = {"./procedures/newsroom/tactus_tools"}
}

newsroom_copywriter = Agent {
    provider = "openai",
    model = "gpt-5.4-mini",
    system_prompt = [[
You are the Papyrus newsroom copywriter agent.

Goal:
- Turn one live copywriting Assignment into complete draft reader-facing copy
  for editor review.
- Consume the selected reporting_context_packet and the private copywriter
  brief attached to the copywriting Assignment.
- Preserve the privacy boundary: reporting packets, doctrine, desk memory,
  unresolved proposed references, and private source notes are not reader copy.

Rules:
- This procedure is dry-run only unless an outer CLI explicitly applies the
  returned plan.
- The Assignment must be copywriting.article-draft or copywriting.brief-draft.
- Do not generate Papyrus persistence snippets or call copywriting plan helpers.
  The outer CLI creates or versions the draft Item deterministically.
- Never create EditionItem placement.
- On rerun, keep the same Item lineage and create the next draft version.
- Treat accepted_reference_ids as usable evidence ids. proposed_references are
  private unresolved prospects and must not be treated as accepted evidence.
- Return structured draft data and a draft record plan.
]],
    tools = {"papyrus", done},
    output = {
        assignment_item_id = field.string{required = true},
        dry_run = field.boolean{required = true},
        work_product_kind = field.string{required = true},
        item_status = field.string{required = true},
        draft_payload = field.object{required = false},
        draft_record_plan = field.object{required = false},
        summary = field.string{required = true}
    }
}

Procedure {
    input = {
        editorial_context_json = field.string{default = "", description = "Resolved editorial context source provenance for the run audit"},
        editorial_context_text = field.string{default = "", description = "Required resolved live editorial context; fetch with papyrus editorial context"},
        editorial_context_hash = field.string{default = "", description = "Resolved editorial context provenance hash"},
        assignment_item_id = field.string{default = "", description = "Papyrus copywriting Assignment.id"},
        corpus_key = field.string{required = true, description = "Papyrus steering corpus key"},
        context_profile = field.string{default = "copywriting", description = "Context profile for copywriting"},
        source_reporting_packet_id = field.string{default = "", description = "Optional reporting_context_packet Message.id override"}
    },
    output = {
        assignment_item_id = field.string{required = true},
        dry_run = field.boolean{required = true},
        work_product_kind = field.string{required = true},
        item_status = field.string{required = true},
        draft_payload = field.object{required = false},
        draft_record_plan = field.object{required = false},
        summary = field.string{required = true}
    },
    function(input)
        if input.editorial_context_text == "" or input.editorial_context_hash == "" then
            error("Resolved editorial context text and hash are required before starting an editorial worker")
        end
        local message = string.format([[
Create a copywriting draft plan for copywriting Assignment %s using corpus %s.

Source reporting packet id override: %s

Required tool flow:
1. Call execute_tactus with one short Tactus snippet.
2. In that snippet, use assignment_context and assignment_agent_context for the
   live copywriting Assignment.
3. Resolve the source reporting_context_packet from Assignment metadata or
   derived_from relations unless source_reporting_packet_id is provided.
4. Return draft_payload with reader-facing title, headline, deck, body
   paragraphs, and evidence notes. Do not call Papyrus persistence planners.
5. Do not create EditionItem placement.

Return dry_run=true, work_product_kind="draft_item", item_status="draft",
draft_payload, and a concise summary.
]], input.assignment_item_id, input.corpus_key, input.source_reporting_packet_id or "")

        local result = newsroom_copywriter({message = input.editorial_context_text .. "\nContext hash: " .. input.editorial_context_hash .. "\n\n" .. message})
        return result.output
    end
}

Specification([[
Feature: Newsroom copywriter procedure
  The copywriter turns selected reporting packets into draft Items only through copywriting Assignments.

  Scenario: Copywriter plans a draft article Item
    Given the procedure has started
    And the input editorial_context_text is "Synthetic test publication policy"
    And the input editorial_context_hash is "synthetic-fixture-context"
    And the input assignment_item_id is "assignment-copywriting-article-123"
    And the input corpus_key is "AI-ML-research"
    And the agent "newsroom_copywriter" calls tool "execute_tactus" with args {"tactus": "local context = assignment_context{ id = \"assignment-copywriting-article-123\" }; local pack = assignment_agent_context{ id = \"assignment-copywriting-article-123\", context_profile = \"copywriting\" }; return { assignment = context.assignment_context.assignment, context = pack }"}
    And the agent "newsroom_copywriter" returns data {"assignment_item_id":"assignment-copywriting-article-123","dry_run":True,"work_product_kind":"draft_item","item_status":"draft","draft_payload":{"title":"Draft article","headline":"Draft article","deck":"Draft from selected packet.","body":["Reader-facing paragraph."]},"summary":"Created one dry-run draft article payload from a selected reporting packet."}
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output item_status should be draft
    And the output draft_payload should exist
]])
