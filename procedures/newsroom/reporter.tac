-- Papyrus automated newsroom reporter procedure.
--
-- Dry-run only: live reporting Assignments produce private reporting context
-- packet payloads for editor selection. The CLI/procedure layer owns all record
-- persistence plans.

Toolset "papyrus" {
    type = "plugin",
    paths = {"./procedures/newsroom/tactus_tools"}
}

newsroom_reporter = Agent {
    provider = "openai",
    model = "gpt-5.4-mini",
    system_prompt = [[
You are the Papyrus newsroom reporter agent.

Goal:
- Turn one live reporting Assignment into a private reporting context packet payload.
- Turn selected packet/copywriting or legacy assignment Item inputs into draft
  article plans only when the input is explicitly in that compatibility path.
- If assignment_json is absent, read either a live Assignment context or a legacy assignment Item.
- If assignment_json is present, use it as the fallback Assignment brief. Live
  context helpers may enrich the packet, but their failure must not by itself
  prevent returning a reporting_context_packet payload.
- When live Assignment context is available, build and use the budgeted Papyrus agent context pack.
- Use execute_tactus as your only tool for Papyrus, Biblicus, Tactus stdlib web research, and context.
- Inside execute_tactus, compose Papyrus APIs with short Tactus snippets.
- Reporter snippets must use the default raw execute_tactus harness. Do not set
  harness="research"; that harness is only for research_packet finalization and
  will reject reporting_context_packet payloads.
- For live reporting assignments, orient from internal Papyrus knowledge first:
  one broad knowledge_query is required before optional web freshness checks.
- If drafting needs fresh source verification, require tactus.web inside the
  snippet and use provider="openai" with web.search or web.synthesize. Treat web
  results as evidence inputs only; do not write GraphQL records from web search.

Rules:
- This is dry-run only. Never claim records were written.
- Live Assignment inputs are workflow records; do not claim, complete, or mutate them unless a separate lifecycle action is requested.
- Live reporting.edition-candidate Assignments must produce a
  reporting_context_packet payload. Do not generate Papyrus persistence snippets
  or call plan_assignment_reporting_context_packet; the outer CLI writes Message,
  ModelAttachment, and SemanticRelation records deterministically.
- Include editor_recommendation, recommended_angle, risk_flags, coverage_gaps,
  open_questions, accepted_reference_ids, proposed_references, and
  copywriter_brief in the reporting payload.
- reporting_context_packet.summary is required and must be a concise one- or
  two-sentence summary of the packet state.
- editor_recommendation must be one of: select, merge, brief, hold, kill.
  If knowledge orientation is blocked or accepted evidence is missing, default
  to hold unless the assignment should be explicitly killed.
- Include knowledge-orientation trace in existing packet fields:
  source_trail plus related metadata fields knowledge_queries,
  papyrus_uris_inspected, and knowledge_blocked_reason when orientation is
  blocked.
- Legacy assignment Item inputs may still normalize to Item.type = "assignment" and mark that compatibility Item drafted in the plan.
- Create a separate draft article Item with Item.type = "article" and Item.status = "draft".
- When live context is available, read and apply its section doctrine, topic-scope context, recent section memory, and accepted evidence before drafting.
- Treat only current accepted references as publishable evidence. Pending
  prospects and rejected scope memory are private curation/training context, not
  source support for reader-facing claims.
- Return structured draft data and the dry-run update plan.
]],
    tools = {"papyrus"},
    output = {
        assignment_item_id = field.string{required = true},
        dry_run = field.boolean{required = true},
        work_product_kind = field.string{required = true},
        item_status = field.string{required = true},
        reporting_context_packet = field.object{required = false},
        reporting_record_plan = field.object{required = false},
        draft_record_plan = field.object{required = false},
        summary = field.string{required = true}
    }
}

Procedure {
    input = {
        assignment_item_id = field.string{default = "", description = "Papyrus Assignment.id or legacy assignment Item.id"},
        assignment_json = field.string{default = "", description = "Inline Assignment or assignment Item JSON for deterministic tests or offline runs"},
        corpus_key = field.string{required = true, description = "Papyrus steering corpus key"},
        context_profile = field.string{default = "", description = "Optional live context profile override"},
        max_evidence_items = field.integer{default = 5, description = "Maximum Biblicus evidence items to use"},
        knowledge_query_scope = field.object{required = false, description = "Optional knowledge-query scope filters for assignment and note retrieval defaults"},
        source_research_assignment_id = field.string{default = "", description = "Optional source research Assignment.id for packet lineage"},
        source_research_packet_id = field.string{default = "", description = "Optional source research packet Message.id for packet lineage"},
        source_research_packet_path = field.string{default = "", description = "Optional dry-run source research packet path for operator traceability"}
    },
    output = {
        assignment_item_id = field.string{required = true},
        dry_run = field.boolean{required = true},
        work_product_kind = field.string{required = true},
        item_status = field.string{required = true},
        reporting_context_packet = field.object{required = false},
        reporting_record_plan = field.object{required = false},
        draft_record_plan = field.object{required = false},
        summary = field.string{required = true}
    },
    function(input)
        local assignment_source = input.assignment_item_id
        if input.assignment_json ~= "" then
            assignment_source = "inline assignment_json"
        end

        local inline_assignment_json = input.assignment_json or ""
        local inline_brief = ""
        if inline_assignment_json ~= "" then
            inline_brief = string.format([[

Inline reporting Assignment JSON is available for fallback use:
%s
]], inline_assignment_json)
        end

        local function normalize_string_list(value, fallback)
            local normalized = {}
            local seen = {}
            local function append(entry)
                if type(entry) ~= "string" then return end
                local trimmed = string.gsub(entry, "^%s+", "")
                trimmed = string.gsub(trimmed, "%s+$", "")
                if trimmed == "" or seen[trimmed] then return end
                seen[trimmed] = true
                table.insert(normalized, trimmed)
            end
            if type(value) == "table" then
                for _, entry in pairs(value) do
                    append(entry)
                end
            end
            if #normalized == 0 and type(fallback) == "table" then
                for _, entry in ipairs(fallback) do
                    append(entry)
                end
            end
            return normalized
        end

        local function lua_list_literal(values)
            local parts = {}
            for _, value in ipairs(values) do
                table.insert(parts, string.format("%q", value))
            end
            return "{" .. table.concat(parts, ", ") .. "}"
        end

        local scope_defaults = {
            includeObjectKinds = {"reference", "item", "category", "semanticNode", "newsroomSection", "assignment", "message"},
            includeMessageKinds = {"note"},
            includeAssignmentTypeKeys = {"research.*", "reporting.*"},
        }
        local requested_scope = input.knowledge_query_scope
        if type(requested_scope) ~= "table" then
            requested_scope = {}
        end
        local include_object_kinds = normalize_string_list(
            requested_scope.includeObjectKinds or requested_scope.include_object_kinds,
            scope_defaults.includeObjectKinds
        )
        local include_message_kinds = normalize_string_list(
            requested_scope.includeMessageKinds or requested_scope.include_message_kinds,
            scope_defaults.includeMessageKinds
        )
        local include_assignment_type_keys = normalize_string_list(
            requested_scope.includeAssignmentTypeKeys or requested_scope.include_assignment_type_keys,
            scope_defaults.includeAssignmentTypeKeys
        )
        local knowledge_scope_snippet = string.format([[
local knowledge_scope = {
    includeObjectKinds = %s,
    includeMessageKinds = %s,
    includeAssignmentTypeKeys = %s,
}
]], lua_list_literal(include_object_kinds), lua_list_literal(include_message_kinds), lua_list_literal(include_assignment_type_keys))

        local message = string.format([[
Create a reporting work-product plan for target reporting assignment %s using corpus %s.

Source research assignment id: %s
Source research packet id: %s
Source research packet path: %s
%s

Required tool flow:
1. Call execute_tactus with one short Tactus snippet.
2. For live Assignment queue work, use the target reporting Assignment id
   "%s" for assignment_context and assignment_agent_context. Do not use the
   source research Assignment id as the target context; source research ids are
   lineage inputs only.
3. Convert live context with this exact shape:
   local ctx = assignment_context{ id = "%s" }
   local pack = assignment_agent_context{ id = "%s", context_profile = "reporting" }
   local item = assignment_context_to_item{ assignment_context = ctx.assignment_context }
   %s
4. For live Assignment queue work, run one broad knowledge_query seeded from
   assignment target/brief before deciding optional web checks. Include
   knowledge trace in source_trail and related metadata fields.
   For assignment-oriented retrieval, include assignment + note scope
   filters in that broad knowledge_query call, for example:
   local knowledge = knowledge_query{
       query = "broad assignment-focused query",
       profile = "reporting",
       output = { format = "structured", maxTokens = 700, seeAlsoMaxTokens = 80 },
       top_k = 10,
       depth = 1,
       includeObjectKinds = knowledge_scope.includeObjectKinds,
       includeMessageKinds = knowledge_scope.includeMessageKinds,
       includeAssignmentTypeKeys = knowledge_scope.includeAssignmentTypeKeys
   }
5. Optionally run anchored knowledge_query (uri/objectUri) or papyrus.resolve_uri
   follow-up when specific internal hits need inspection.
6. Use item_get only when live Assignment context is unavailable.
7. For live reporting.edition-candidate Assignments, return a reporting_context_packet payload only.
8. When fresh source verification is needed, use local web = require("tactus.web") and call web.search or web.synthesize inside execute_tactus after internal orientation.
   A zero-result first search is not terminal; continue through bounded diversified retries and only mark blocked when discovery is exhausted.
9. Do not call Papyrus persistence planners. The outer CLI builds any record plan.
10. When source research ids are provided, include source_research_assignment_id
   and source_research_packet_id in the reporting payload so the packet plan can
   write derived_from lineage.
11. If live context helpers fail but assignment_json is present, return a packet
   from the assignment_json brief and mark the context gap in risk_flags and
   open_questions.
12. Use raw execute_tactus only. Do not set harness="research" in this reporter
   procedure.
13. Strict path: use one deterministic execute_tactus snippet that performs
    assignment_context + assignment_agent_context + one broad scoped
    knowledge_query, then returns reporting_context_packet directly.

For live reporting assignments, return assignment_item_id="%s", dry_run=true, work_product_kind="reporting_context_packet", item_status="reported", reporting_context_packet, and a concise summary.
For legacy draft compatibility, return dry_run=true, work_product_kind="draft_article", item_status="draft", draft_record_plan, and a concise summary.
Set reporting_context_packet.editor_recommendation to exactly one enum value:
select, merge, brief, hold, or kill.
Set reporting_context_packet.summary to a concise packet-level summary.
]], assignment_source, input.corpus_key, input.source_research_assignment_id or "", input.source_research_packet_id or "", input.source_research_packet_path or "", inline_brief, input.assignment_item_id or "", input.assignment_item_id or "", input.assignment_item_id or "", knowledge_scope_snippet, input.assignment_item_id or "")

        local json = require("tactus.io.json")

        local function decode_last_json_object(text)
            if type(text) ~= "string" or text == "" then return nil end
            local close_index = string.match(text, ".*()}")
            if not close_index then return nil end
            for start = close_index, 1, -1 do
                if string.sub(text, start, start) == "{" then
                    local candidate = string.sub(text, start, close_index)
                    local ok, decoded = pcall(json.decode, candidate)
                    if ok and type(decoded) == "table" then
                        return decoded
                    end
                end
            end
            return nil
        end

        local function normalize_agent_output(result_payload)
            local output = {}
            if result_payload ~= nil and result_payload.output ~= nil then
                output = result_payload.output
            else
                output = result_payload
            end
            if type(output) == "table" and type(output.value) == "table" then
                output = output.value
            end
            if type(output) == "string" then
                local ok, decoded = pcall(json.decode, output)
                if ok and type(decoded) == "table" then
                    output = decoded
                else
                    local extracted = decode_last_json_object(output)
                    if type(extracted) == "table" then
                        output = extracted
                    else
                        output = {
                            assignment_item_id = input.assignment_item_id,
                            dry_run = true,
                            work_product_kind = "reporting_context_packet",
                            item_status = "reported",
                            summary = "Reporter returned unstructured text instead of a reporting context packet.",
                            validation_failures = {"reporter_output_not_structured"},
                        }
                    end
                end
            end
            if type(output) ~= "table" then
                output = {
                    assignment_item_id = input.assignment_item_id,
                    dry_run = true,
                    work_product_kind = "reporting_context_packet",
                    item_status = "reported",
                    summary = "Reporter returned no structured reporting context packet.",
                    validation_failures = {"reporter_output_missing"},
                }
            end
            return output
        end

        local function has_required_reporting_output(output)
            if type(output) ~= "table" then return false, "output_not_table" end
            if type(output.work_product_kind) ~= "string" or output.work_product_kind == "" then
                return false, "missing_work_product_kind"
            end
            if output.work_product_kind ~= "reporting_context_packet" then
                return true, nil
            end
            local packet = output.reporting_context_packet
            if type(packet) ~= "table" then return false, "missing_reporting_context_packet" end
            if type(packet.summary) ~= "string" or packet.summary == "" then
                return false, "missing_reporting_summary"
            end
            local recommendation = packet.editor_recommendation or packet.editorRecommendation
            if type(recommendation) ~= "string" or recommendation == "" then
                return false, "missing_editor_recommendation"
            end
            return true, nil
        end

        local max_attempts = 2
        local attempt = 1
        local validation_failures = {}
        local output = {}
        local retry_message = message
        while attempt <= max_attempts do
            local result = newsroom_reporter({message = retry_message})
            output = normalize_agent_output(result)
            local ok, failure = has_required_reporting_output(output)
            if ok then
                break
            end
            if failure ~= nil then
                table.insert(validation_failures, tostring(failure))
            else
                table.insert(validation_failures, "unknown_reporting_validation_failure")
            end
            if attempt >= max_attempts then
                break
            end
            retry_message = string.format([[
The previous response failed strict reporting output validation.

Validation failure:
%s

Return a single structured object only with:
- assignment_item_id
- dry_run=true
- work_product_kind="reporting_context_packet"
- item_status="reported"
- reporting_context_packet
- summary

Do not return prose. Do not call done.

Original instructions:
%s
]], tostring(validation_failures[#validation_failures]), message)
            attempt = attempt + 1
        end
        if #validation_failures > 0 then
            output.validation_failures = validation_failures
            output.retry_count = math.max(0, attempt - 1)
        end
        if output.assignment_item_id == nil or output.assignment_item_id == "" then
            output.assignment_item_id = input.assignment_item_id
        end
        if output.dry_run == nil then
            output.dry_run = true
        end
        if output.work_product_kind == nil or output.work_product_kind == "" then
            if output.reporting_context_packet ~= nil then
                output.work_product_kind = "reporting_context_packet"
            elseif output.draft_record_plan ~= nil then
                output.work_product_kind = "draft_article"
            else
                output.work_product_kind = "reporting_context_packet"
            end
        end
        if output.item_status == nil or output.item_status == "" then
            if output.work_product_kind == "draft_article" then
                output.item_status = "draft"
            else
                output.item_status = "reported"
            end
        end
        if output.summary == nil or output.summary == "" then
            if output.reporting_context_packet ~= nil then
                output.summary = "Created one dry-run reporting context packet payload."
            elseif output.draft_record_plan ~= nil then
                output.summary = "Created one dry-run draft article plan."
            else
                output.summary = "No reporting payload was returned."
            end
        end
        if output.work_product_kind == "reporting_context_packet" and type(output.reporting_context_packet) ~= "table" then
            output.reporting_context_packet = {
                summary = output.summary,
                editor_recommendation = "hold",
                recommended_angle = "Reporting packet could not be structured; rerun with refreshed context.",
                risk_flags = {
                    "reporting_payload_missing_or_unstructured",
                },
                coverage_gaps = {
                    "No structured reporting context packet was returned by the reporter agent.",
                },
                open_questions = {
                    "Rerun reporting with refreshed assignment context and verify tool outputs.",
                },
                accepted_reference_ids = {},
                proposed_references = {},
                verification_needs = {
                    "Re-run reporting_context_packet generation; prior output was unstructured.",
                },
                source_trail = {
                    {
                        source_kind = "reporter_fallback",
                        note = "No structured reporting_context_packet returned.",
                    }
                },
                knowledge_queries = {},
                papyrus_uris_inspected = {},
                knowledge_blocked_reason = "reporting_payload_missing_or_unstructured",
                knowledge_orientation_attempted = true,
                knowledge_orientation_completed = false,
                reporting_path_mode = "strict_single_path",
                copywriter_brief = "Hold for editor review; regenerate reporting packet before copywriting intake.",
            }
        end
        if type(output.reporting_context_packet) == "table" then
            local packet = output.reporting_context_packet
            if type(packet.summary) ~= "string" or packet.summary == "" then
                packet.summary = output.summary
            end
            local recommendation = packet.editor_recommendation or packet.editorRecommendation
            local normalized = string.lower(tostring(recommendation or ""))
            normalized = string.gsub(normalized, "[^a-z]", "")
            local allowed = {
                select = true,
                merge = true,
                brief = true,
                hold = true,
                kill = true,
            }
            if not allowed[normalized] then
                local blocked_reason = packet.knowledge_blocked_reason or packet.knowledgeBlockedReason
                local has_accepted = type(packet.accepted_reference_ids) == "table" and next(packet.accepted_reference_ids) ~= nil
                if type(blocked_reason) == "string" and blocked_reason ~= "" then
                    normalized = "hold"
                elseif not has_accepted then
                    normalized = "hold"
                else
                    normalized = "brief"
                end
            end
            packet.editor_recommendation = normalized
            if packet.reporting_path_mode == nil or packet.reporting_path_mode == "" then
                packet.reporting_path_mode = "strict_single_path"
            end
            local blocked_reason = packet.knowledge_blocked_reason or packet.knowledgeBlockedReason
            if packet.knowledge_orientation_attempted == nil then
                packet.knowledge_orientation_attempted =
                    (type(packet.knowledge_queries) == "table" and next(packet.knowledge_queries) ~= nil)
                    or (type(packet.source_trail) == "table" and next(packet.source_trail) ~= nil)
                    or (type(blocked_reason) == "string" and blocked_reason ~= "")
            end
            if packet.knowledge_orientation_completed == nil then
                packet.knowledge_orientation_completed =
                    packet.knowledge_orientation_attempted == true
                    and not (type(blocked_reason) == "string" and blocked_reason ~= "")
            end
            if type(packet.proposed_references) == "table" and next(packet.proposed_references) ~= nil then
                if type(packet.verification_needs) ~= "table" or next(packet.verification_needs) == nil then
                    packet.verification_needs = {
                        "Verify each proposed reference before editor selection or copywriting intake.",
                    }
                end
            end
            output.reporting_context_packet = packet
        end
        return output
    end
}

Specification([[
Feature: Newsroom reporter procedure
  The reporter creates private reporting packet payloads for live reporting Assignments and keeps legacy draft planning compatible.

  Scenario: Reporter returns a legacy draft update plan
    Given the procedure has started
    And the input assignment_item_id is "assignment-abc123"
    And the input corpus_key is "AI-ML-research"
    And the agent "newsroom_reporter" calls tool "execute_tactus" with args {"tactus": "local item = item_get{ id = \"assignment-abc123\" }; local evidence = biblicus_query{ corpus_key = \"AI-ML-research\", query = \"AI Agents Enter the Lab\", max_total_items = 5 }; return { item = item, evidence = evidence }"}
    And the agent "newsroom_reporter" returns data {"assignment_item_id":"assignment-abc123","dry_run":True,"work_product_kind":"draft_article","item_status":"draft","draft_record_plan":{"dryRun":True,"lifecycle":"draft","records":[{"modelName":"Item","action":"update","input":{"id":"assignment-abc123","type":"assignment","status":"drafted","typeStatus":"assignment#drafted"}},{"modelName":"Item","action":"create","input":{"type":"article","status":"draft","typeStatus":"article#draft"}}]},"summary":"Created one dry-run draft article plan."}
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output item_status should be draft
    And the output draft_record_plan should exist

  Scenario: Reporter accepts a live reporting Assignment context
    Given the procedure has started
    And the input assignment_item_id is "assignment-live-123"
    And the input corpus_key is "AI-ML-research"
    And the input context_profile is "reporting"
    And the agent "newsroom_reporter" calls tool "execute_tactus" with args {"tactus": "local context = assignment_context{ id = \"assignment-live-123\" }; local pack = assignment_agent_context{ id = \"assignment-live-123\", context_profile = \"reporting\" }; local knowledge = knowledge_query{ query = \"assignment-live-123 reporting focus\", profile = \"reporting\", format = \"both\", max_tokens = 1200, top_k = 12, depth = 1 }; return { assignment = context.assignment_context.assignment, context = pack, knowledge = knowledge }"}
    And the agent "newsroom_reporter" returns data {"assignment_item_id":"assignment-live-123","dry_run":True,"work_product_kind":"reporting_context_packet","item_status":"reported","reporting_context_packet":{"summary":"Reporting context ready.","editor_recommendation":"hold","recommended_angle":"Reader impact.","risk_flags":["Verify one claim."],"coverage_gaps":["Need second source."],"open_questions":["Who is affected?"],"accepted_reference_ids":[],"proposed_references":[],"source_trail":[{"source_kind":"knowledge_query","note":"Oriented to accepted internal context."}],"knowledge_queries":["assignment-live-123 reporting focus"],"papyrus_uris_inspected":[],"copywriter_brief":"Use the packet after editor selection."},"summary":"Created one dry-run reporting context packet payload from a live assignment context."}
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output item_status should be reported
    And the output reporting_context_packet should exist
]])
