-- Papyrus automated newsroom researcher procedure.
--
-- Dry-run only: live Assignments return research packet payloads; the
-- CLI/procedure layer owns deterministic Message-backed persistence plans.

Toolset "papyrus" {
    type = "plugin",
    paths = {"./procedures/newsroom/tactus_tools"}
}

newsroom_researcher = Agent {
    provider = "openai",
    model = "gpt-6-luna",
    system_prompt = [[
You are the Papyrus newsroom researcher agent.

Goal:
- Build an evidence-backed research packet for one live Assignment or legacy assignment Item.
- If assignment_json is absent, read either a live Assignment context or a legacy assignment Item.
- When live Assignment context is available, build and use the budgeted Papyrus agent context pack.
- Use execute_tactus as your only tool for Papyrus, Biblicus, Tactus stdlib web research, and context.
- Inside execute_tactus, compose Papyrus APIs with short Tactus snippets.
- When fresh external evidence is needed, require tactus.web inside the snippet:
  local web = require("tactus.web"). Use provider="openai" for both web.search
  and web.synthesize through the OpenAI web_search API. Keep provider selection
  explicit and do not write GraphQL records from web results.

Rules:
- This is dry-run only. Never claim records were written.
- Live Assignment inputs must produce a research_packet payload; do not mutate Assignment.status or generate persistence snippets.
- Legacy assignment Item inputs may still produce the compatibility Item update plan and attach research under editorial.newsroom.research.
- When live context is available, read and apply its section doctrine, topic-scope context, recent section memory, and fresh-evidence instructions.
- Apply doctrine in this order when context is available: publication mission
  and policies, section mission and policies, assignment brief, topic-scope
  metadata, recent section memory, then fresh evidence instructions.
- Treat publication doctrine as the global editorial constitution and section
  doctrine as the local desk standard. If doctrine and assignment instructions
  conflict, surface the conflict in openQuestions or coverageGaps.
- Do not quote private doctrine, curation notes, or unpublished assignment
  material into reader-facing prose. Use doctrine to guide judgment, source
  selection, coverage gaps, and recommendedAngle.
- Use only current accepted references as publishable evidence or desk-memory
  context. Pending references are reference prospects. Rejected references are
  scope memory only unless the task is explicitly curation or classifier
  training.
- When proposing a new reference for ingestion, include an ingestion rationale:
  a brief summary of what the source material is about, how it relates to the
  current research focus, and how it fits the publication mission.
- Return doctrine_context, comparison_findings, and rubric_assessments when the research packet needs to explain why evidence did or did not meet the live doctrine standard.
- Return structured research data. Existing research_record_plan output is compatibility diagnostics; the CLI write path is the source of truth.
- The final response must be the structured output object matching the declared
  output schema. Return a structured object, not a JSON string. Do not rewrite,
  reformat, summarize, or augment the execute_tactus.value object. Do not
  return Markdown, bullets, or explanatory prose as the final answer.
]],
    tools = {"papyrus"},
    output = {
        assignment_item_id = field.string{required = true},
        corpus_key = field.string{required = true},
        dry_run = field.boolean{required = true},
        item_status = field.string{required = true},
        research_packet = field.object{required = true},
        research_record_plan = field.object{required = true},
        summary = field.string{required = true}
    }
}

Procedure {
    input = {
        editorial_context_json = field.string{default = "", description = "Resolved editorial context source provenance for the run audit"},
        editorial_context_text = field.string{default = "", description = "Required resolved live editorial context; fetch with papyrus editorial context"},
        editorial_context_hash = field.string{default = "", description = "Resolved editorial context provenance hash"},
        assignment_item_id = field.string{default = "", description = "Papyrus Assignment.id or legacy assignment Item.id"},
        assignment_json = field.string{default = "", description = "Inline Assignment or assignment Item JSON for deterministic tests or offline runs"},
        corpus_key = field.string{required = true, description = "Papyrus steering corpus key"},
        context_profile = field.string{default = "", description = "Optional live context profile override"},
        research_questions = field.string{default = "", description = "Optional editor/reporter research questions"},
        max_evidence_items = field.integer{default = 20, description = "Maximum Biblicus evidence items to use"}
    },
    output = {
        assignment_item_id = field.string{required = true},
        corpus_key = field.string{required = true},
        dry_run = field.boolean{required = true},
        item_status = field.string{required = true},
        research_packet = field.object{required = true},
        research_record_plan = field.object{required = true},
        summary = field.string{required = true}
    },
    function(input)
        if input.editorial_context_text == "" or input.editorial_context_hash == "" then
            error("Resolved editorial context text and hash are required before starting an editorial worker")
        end
        local json = require("tactus.io.json")

        local function json_string(value)
            local text = tostring(value or "")
            text = string.gsub(text, "\\", "\\\\")
            text = string.gsub(text, '"', '\\"')
            text = string.gsub(text, "\n", "\\n")
            text = string.gsub(text, "\r", "\\r")
            return '"' .. text .. '"'
        end

        local function json_value(value)
            if type(value) == "table" then
                local parts = {}
                for _, entry in ipairs(value) do
                    table.insert(parts, json_string(entry))
                end
                return "[" .. table.concat(parts, ",") .. "]"
            end
            return json_string(value)
        end

        local function assignment_json_for_tool(value)
            if type(value) == "string" then
                return value
            end
            if type(value) ~= "table" then
                return ""
            end
            if value.assignmentTypeKey or value.assignment_type_key then
                local id = value.id or "assignment-inline"
                local assignment_type_key = value.assignmentTypeKey or value.assignment_type_key
                local queue_key = value.queueKey or value.queue_key or assignment_type_key
                local queue_status_key = value.queueStatusKey or value.queue_status_key or (queue_key .. "#" .. tostring(value.status or "open"))
                local status = value.status or "open"
                local title = value.title or id
                local brief = value.brief or value.summary or ""
                local section_id = value.sectionId or value.section_id
                local section_key = value.sectionKey or value.section_key
                local section_type = value.sectionType or value.section_type
                local primary_focus = value.primaryFocusCategoryKey or value.primary_focus_category_key
                local metadata = value.metadata or {}
                local metadata_parts = {}
                if type(metadata) == "table" then
                    local metadata_fields = {
                        "sectionId",
                        "sectionKey",
                        "sectionTitle",
                        "sectionType",
                        "sectionMission",
                        "sectionPolicies",
                        "assignmentGuidance",
                        "killCriteria",
                        "visualGuidance",
                        "primaryFocusCategoryKey",
                        "topicScopeCategoryKeys",
                        "deskCategoryKey",
                        "deskCategoryLineageId",
                        "deskCategoryTitle",
                        "focusCategoryKey",
                        "focusCategoryLineageId",
                        "focusCategoryTitle",
                        "contextProfile",
                        "contextTokenBudget",
                        "targetSystemType",
                    }
                    for _, key in ipairs(metadata_fields) do
                        if metadata[key] ~= nil then
                            table.insert(metadata_parts, json_string(key) .. ":" .. json_value(metadata[key]))
                        end
                    end
                end
                return table.concat({
                    "{",
                    '"id":', json_string(id), ",",
                    '"assignmentTypeKey":', json_string(assignment_type_key), ",",
                    '"queueKey":', json_string(queue_key), ",",
                    '"queueStatusKey":', json_string(queue_status_key), ",",
                    '"status":', json_string(status), ",",
                    '"sectionId":', json_string(section_id), ",",
                    '"sectionKey":', json_string(section_key), ",",
                    '"sectionType":', json_string(section_type), ",",
                    '"primaryFocusCategoryKey":', json_string(primary_focus), ",",
                    '"title":', json_string(title), ",",
                    '"brief":', json_string(brief), ",",
                    '"metadata":{', table.concat(metadata_parts, ","), "}",
                    "}",
                })
            end
            local id = value.id or "assignment-inline"
            local status = value.status or "dispatched"
            local type_status = value.typeStatus or value.type_status or "assignment#dispatched"
            local section = value.section or "Research"
            local title = value.title or value.headline or id
            local summary = value.summary or ""
            return table.concat({
                "{",
                '"id":', json_string(id), ",",
                '"type":"assignment",',
                '"status":', json_string(status), ",",
                '"typeStatus":', json_string(type_status), ",",
                '"section":', json_string(section), ",",
                '"title":', json_string(title), ",",
                '"summary":', json_string(summary), ",",
                '"editorial":{"newsroom":{"assignment":{"brief":', json_string(summary), "}}}",
                "}",
            })
        end

        local assignment_json = assignment_json_for_tool(input.assignment_json)
        local assignment_source = input.assignment_item_id
        local inline_assignment_id = ""
        if assignment_json ~= "" then
            assignment_source = "inline assignment_json"
            inline_assignment_id = string.match(assignment_json, '"id"%s*:%s*"([^"]+)"') or ""
        end

        local message = string.format([[
Create a research packet and dry-run update plan for %s using corpus %s.

Research questions:
%s

Inline assignment JSON, when present:
%s

Inline assignment id to preserve, when present:
%s

Required tool flow:
1. Call execute_tactus exactly once with harness="research", corpus_key set to
   %s, and max_evidence_items set to %d.
2. The harness already loads tactus.web, the assignment item, the corpus key,
   and the dry-run plan builder. Do not require any modules and do not choose a
   web provider.
3. If inline assignment JSON is present, pass assignment_item_json. If not,
   pass assignment_id set to %s so the harness can read the live Assignment.
4. Your tactus argument should be only a small body snippet that uses:
   - assignment: the preloaded assignment table.
   - corpus_key: the preloaded corpus key.
   - max_evidence_items: the evidence limit.
   - web_search(query): OpenAI-backed web search with the standard model and budget.
   - finish_research(research): validates and returns the dry-run output object.
   - finish_research_from_search(search, options): builds the standard research
     packet from one web_search result, including source_snapshots and
     proposed_references with ingestion_rationale.
5. Web search results are not accepted References yet. Put them in
   source_snapshots and proposed_references. Do not put web
   evidence_candidate_id values in evidence_item_ids.
6. Live Assignment runs must produce a research packet Message plan, not an
   assignment Item update plan. The harness handles that routing.

Use this body snippet shape:
local search = web_search("specific current query for this assignment")
return finish_research_from_search(search, {
    recommended_angle = "Non-promotional editorial angle.",
})

Do not copy example placeholder strings. Use a specific query and specific
recommended_angle that reflect the research question.

Use at most %d evidence items. Return dry_run=true, item_status="researched",
research_packet, research_record_plan, and a concise summary.
Your final response must be exactly the structured object returned by execute_tactus.value.
Do not convert it to JSON text. Do not add an ok field. Do not rewrite nested
metadata, ingestion rationales, or record plans.
]], assignment_source, input.corpus_key, input.research_questions, assignment_json, inline_assignment_id, input.corpus_key, input.max_evidence_items, assignment_source, input.max_evidence_items)

        local result = newsroom_researcher({message = input.editorial_context_text .. "\nContext hash: " .. input.editorial_context_hash .. "\n\n" .. message})
        local output = result.output
        if type(output) == "string" and output ~= "" then
            local ok, decoded = pcall(json.decode, output)
            if not ok then
                error("newsroom_researcher returned text instead of the structured execute_tactus.value object")
            end
            output = decoded
        end
        if type(output) == "table" then
            local payload = output
            if type(output.value) == "table" then
                payload = output.value
            end
            return {
                assignment_item_id = payload.assignment_item_id or payload.assignmentItemId or input.assignment_item_id or inline_assignment_id or "assignment-unknown",
                corpus_key = payload.corpus_key or payload.corpusKey or input.corpus_key,
                dry_run = payload.dry_run,
                item_status = payload.item_status or payload.itemStatus or "researched",
                research_packet = payload.research_packet or payload.researchPacket or {},
                research_record_plan = payload.research_record_plan or payload.researchRecordPlan or {},
                summary = payload.summary or "Created dry-run research packet.",
            }
        end
        return output
    end
}

Specification([[
Feature: Newsroom researcher procedure
  The researcher creates dry-run research update plans for assignment Items.

  Scenario: Researcher returns a research update plan
    Given the procedure has started
    And the input editorial_context_text is "Synthetic test publication policy"
    And the input editorial_context_hash is "synthetic-fixture-context"
    And the input assignment_item_id is "assignment-abc123"
    And the input corpus_key is "AI-ML-research"
    And the input context_profile is "analysis"
    And the input max_evidence_items is 2
    And the input research_questions is "What concrete lab workflow examples support this?"
    And the agent "newsroom_researcher" calls tool "execute_tactus" with args {"tactus": "local item = item_get{ id = \"assignment-abc123\" }; local steering = biblicus_steering_artifacts{ corpus_key = \"AI-ML-research\" }; return { item = item, steering = steering }"}
    And the agent "newsroom_researcher" returns data {"assignment_item_id":"assignment-abc123","corpus_key":"AI-ML-research","dry_run":True,"item_status":"researched","research_packet":{"summary":"Evidence supports a practical research-workflow angle.","evidence_item_ids":["research-001"]},"research_record_plan":{"dryRun":True,"lifecycle":"assignment-research","records":[{"modelName":"Item","action":"update","input":{"id":"assignment-abc123","type":"assignment","status":"researched","typeStatus":"assignment#researched"}}]},"summary":"Created one dry-run research update plan."}
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output item_status should be researched
    And the output research_record_plan should exist

  Scenario: Researcher accepts a live Assignment context
    Given the procedure has started
    And the input editorial_context_text is "Synthetic test publication policy"
    And the input editorial_context_hash is "synthetic-fixture-context"
    And the input assignment_item_id is "assignment-live-123"
    And the input corpus_key is "AI-ML-research"
    And the input context_profile is "reporting"
    And the agent "newsroom_researcher" calls tool "execute_tactus" with args {"tactus": "local context = assignment_context{ id = \"assignment-live-123\" }; local pack = assignment_agent_context{ id = \"assignment-live-123\", context_profile = \"reporting\" }; local item = assignment_context_to_item{ assignment_context = context.assignment_context }; return { context = context, pack = pack, item = item }"}
    And the agent "newsroom_researcher" returns data {"assignment_item_id":"assignment-live-123","corpus_key":"AI-ML-research","dry_run":True,"item_status":"researched","research_packet":{"summary":"Live assignment context normalized correctly."},"research_record_plan":{"dryRun":True,"lifecycle":"assignment-research"},"summary":"Created one dry-run research update plan from a live assignment context."}
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output item_status should be researched
    And the output research_record_plan should exist
]])
