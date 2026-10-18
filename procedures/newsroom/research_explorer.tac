-- Papyrus knowledge-aware exploratory newsroom researcher.
--
-- Dry-run only: this procedure produces the same Message-backed research
-- packet contract as researcher.tac, but allows a bounded knowledge/web loop.

Toolset "papyrus" {
    type = "plugin",
    paths = {"./procedures/newsroom/tactus_tools"}
}

newsroom_research_explorer = Agent {
    provider = "openai",
    model = "gpt-5.4-mini",
    system_prompt = [[
You are the Papyrus exploratory newsroom researcher agent.

Goal:
- Build a research_packet payload for one live Assignment or legacy assignment
  Item. The outer CLI/procedure layer owns deterministic Message,
  ModelAttachment, and SemanticRelation persistence.
- Use execute_tactus as your only tool.
- Explore internal knowledge before using web search unless the assignment explicitly asks for current external evidence.
- Produce the same dry-run research packet payload contract as the constrained researcher.
- Respect research_mode:
  - internal_brief: synthesize internal Papyrus knowledge only.
  - source_discovery: orient with internal knowledge, then perform web search for new reference prospects.
  - full_research: internal orientation, web discovery, and integrated synthesis.

Allowed tool strategy:
- You may call execute_tactus at most 6 times total.
- Use at most 3 knowledge_query calls, 2 Papyrus URI lookups, and 2 web searches.
- Always finish with one execute_tactus call using harness="research" so finish_research(...) or finish_research_from_search(...) builds the standard dry-run plan.
- Helper scope is strict: knowledge_search, web_search, finish_research,
  finish_research_from_search, evidence_item_ids_from_knowledge, and
  proposed_references_from_search only exist inside execute_tactus calls that
  set harness="research". Never call those helpers in a raw execute_tactus
  snippet. Raw snippets may use assignment_context, assignment_agent_context,
  knowledge_query, papyrus.resolve_uri, and papyrus.reference.web_search only.

Required policy sequence:
1. Read assignment context and budgeted agent context when assignment_id is live.
2. Run one broad knowledge_query using compact researcher context: higher top_k, low per-source detail, source diversity, and a small token budget.
3. Optionally inspect promising papyrus:// URIs with papyrus.resolve_uri or anchored knowledge_query follow-ups.
4. Use OpenAI web search only for freshness, gaps, or assignment requests for external evidence. In source_discovery and full_research modes, at least one web search is required unless the final packet includes blockedReason.
   The research-harness web_search helper performs bounded deterministic retry diversification; do not stop discovery after a zero-result first attempt.
5. Finalize a packet with researchTrace: queries run, Papyrus URIs inspected, web searches run, accepted evidence ids selected, proposed references, and unresolved gaps.

Evidence rules:
- Only current accepted Papyrus Reference hits may populate evidence_item_ids.
- Web search results are source-material prospects only; put them in source_snapshots and proposed_references with ingestion_rationale.
- Never put web evidence_candidate_id values in evidence_item_ids.
- Keep evidence_item_ids to at most 8 accepted records.

Editorial rules:
- Apply publication doctrine first, then section/desk doctrine, assignment brief, topic scope, accepted evidence, and recent activity.
- Do not quote private doctrine or unpublished assignment material into reader-facing prose.
- Surface conflicts, missing evidence, and uncertainty in open_questions or coverage_gaps.

Final response:
- Return the structured object from execute_tactus.value.
- Do not convert it to JSON text and do not add commentary.
]],
    tools = {"papyrus"},
    output = {
        assignment_item_id = field.string{required = true},
        corpus_key = field.string{required = true},
        dry_run = field.boolean{required = true},
        item_status = field.string{required = true},
        research_packet = field.object{required = true},
        research_record_plan = field.object{required = true},
        summary = field.string{required = true},
        recovery_path = field.string{required = false},
        retry_count = field.integer{required = false},
        validation_failures = field.array{required = false}
    }
}

Procedure {
    input = {
        assignment_item_id = field.string{default = "", description = "Papyrus Assignment.id or legacy assignment Item.id"},
        assignment_json = field.string{default = "", description = "Inline Assignment or assignment Item JSON for deterministic tests"},
        corpus_key = field.string{required = true, description = "Papyrus steering corpus key"},
        context_profile = field.string{default = "researcher", description = "Optional live context profile override"},
        research_mode = field.string{default = "source_discovery", description = "internal_brief, source_discovery, or full_research"},
        research_questions = field.string{default = "", description = "Optional editor/reporter research questions"},
        max_evidence_items = field.integer{default = 20, description = "Maximum accepted Papyrus evidence ids to use"},
        knowledge_query_scope = field.object{required = false, description = "Optional knowledge-query scope filters for assignment and note retrieval defaults"}
    },
    output = {
        assignment_item_id = field.string{required = true},
        corpus_key = field.string{required = true},
        dry_run = field.boolean{required = true},
        item_status = field.string{required = true},
        research_packet = field.object{required = true},
        research_record_plan = field.object{required = true},
        summary = field.string{required = true},
        recovery_path = field.string{required = true},
        retry_count = field.integer{required = true},
        validation_failures = field.array{required = true}
    },
    function(input)
        local json = require("tactus.io.json")

        local assignment_id = input.assignment_item_id or ""
        local assignment_json = ""
        local corpus_key = input.corpus_key
        local research_mode = input.research_mode or "source_discovery"
        local max_evidence_items = input.max_evidence_items or 20
        local max_attempts = 3

        local function percent_decode(text)
            if type(text) ~= "string" then return "" end
            return (string.gsub(text, "%%(%x%x)", function(hex)
                local code = tonumber(hex, 16)
                if not code then return "" end
                return string.char(code)
            end))
        end

        local function normalize_inline_assignment_json(value)
            if type(value) == "table" then
                local ok, encoded = pcall(json.encode, value)
                if ok and type(encoded) == "string" then return encoded end
                return ""
            end
            if type(value) ~= "string" then
                return value == nil and "" or tostring(value)
            end
            if string.sub(value, 1, 9) == "@urljson:" then
                return percent_decode(string.sub(value, 10))
            end
            return value
        end

        assignment_json = normalize_inline_assignment_json(input.assignment_json)
        if assignment_id == "" and assignment_json ~= "" then
            local ok, decoded = pcall(json.decode, assignment_json)
            if ok and type(decoded) == "table" and type(decoded.id) == "string" and decoded.id ~= "" then
                assignment_id = decoded.id
            end
        end

        local function truncate_text(value, limit)
            local text = tostring(value or "")
            if string.len(text) <= limit then return text end
            return string.sub(text, 1, limit) .. "...[truncated]"
        end

        local function normalize_research_mode(value)
            local mode = string.lower(tostring(value or "source_discovery"))
            mode = string.gsub(mode, "%-", "_")
            if mode == "internal_brief" or mode == "source_discovery" or mode == "full_research" then
                return mode
            end
            return "source_discovery"
        end

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

        local function as_table(value)
            if type(value) == "table" then
                local ok_encoded, encoded = pcall(json.encode, value)
                if ok_encoded then
                    local ok_decoded, decoded = pcall(json.decode, encoded)
                    if ok_decoded and type(decoded) == "table" then return decoded end
                end
                return value
            end
            local ok_encoded, encoded = pcall(json.encode, value)
            if not ok_encoded then return nil end
            local ok_decoded, decoded = pcall(json.decode, encoded)
            if ok_decoded and type(decoded) == "table" then return decoded end
            return nil
        end

        local function decode_candidate(output)
            local output_table = as_table(output)
            if output_table then
                local wrapped_value = as_table(output_table.value)
                if wrapped_value then
                    return wrapped_value, output_table
                end
                return output_table, output_table
            end
            if type(output) ~= "string" or output == "" then
                return nil, nil
            end
            local ok, decoded = pcall(json.decode, output)
            if ok and type(decoded) == "table" then
                if type(decoded.value) == "table" then
                    return decoded.value, decoded
                end
                return decoded, decoded
            end
            local extracted = decode_last_json_object(output)
            if type(extracted) == "table" then
                if type(extracted.value) == "table" then
                    return extracted.value, extracted
                end
                return extracted, extracted
            end
            return nil, nil
        end

        local function normalize_payload(payload)
            payload = as_table(payload)
            if type(payload) ~= "table" then return nil end
            local research_packet = payload.research_packet or payload.researchPacket
            local research_packet_table = as_table(research_packet) or {}
            local normalized = {
                assignment_item_id = payload.assignment_item_id or payload.assignmentItemId or assignment_id or "assignment-unknown",
                corpus_key = payload.corpus_key or payload.corpusKey or corpus_key,
                dry_run = payload.dry_run,
                item_status = payload.item_status or payload.itemStatus,
                research_packet = research_packet,
                research_record_plan = payload.research_record_plan or payload.researchRecordPlan,
                summary = payload.summary or research_packet_table.summary,
                recovery_path = payload.recovery_path or payload.recoveryPath,
                retry_count = payload.retry_count or payload.retryCount,
                validation_failures = payload.validation_failures or payload.validationFailures,
            }
            if normalized.dry_run == nil then normalized.dry_run = payload.dryRun end
            return normalized
        end

        local function validate_payload(payload)
            local errors = {}
            if type(payload) ~= "table" then
                table.insert(errors, "payload is not an object")
                return errors
            end
            if type(payload.assignment_item_id) ~= "string" or payload.assignment_item_id == "" then
                table.insert(errors, "assignment_item_id is required")
            end
            if type(payload.corpus_key) ~= "string" or payload.corpus_key == "" then
                table.insert(errors, "corpus_key is required")
            end
            if type(payload.dry_run) ~= "boolean" then
                table.insert(errors, "dry_run must be a boolean")
            end
            if type(payload.item_status) ~= "string" or payload.item_status == "" then
                table.insert(errors, "item_status is required")
            end
            if type(payload.research_packet) ~= "table" then
                table.insert(errors, "research_packet must be an object")
            end
            if type(payload.research_record_plan) ~= "table" then
                table.insert(errors, "research_record_plan must be an object")
            end
            if type(payload.summary) ~= "string" or payload.summary == "" then
                table.insert(errors, "summary is required")
            end
            return errors
        end

        local function encode_for_feedback(value)
            if type(value) == "string" then return value end
            local ok, encoded = pcall(json.encode, value)
            if ok then return encoded end
            return tostring(value)
        end

        local function build_retry_message(base_message, attempt, errors, previous_output)
            local error_text = table.concat(errors, "; ")
            local output_text = truncate_text(encode_for_feedback(previous_output), 6000)
            return string.format([[
%s

The previous response was invalid on attempt %d of %d.
Validation errors:
%s

Previous raw output (for correction):
%s

Corrective requirements:
- Return a structured object, not prose.
- Return ONLY these top-level fields: assignment_item_id, corpus_key, dry_run, item_status, research_packet, research_record_plan, summary.
- dry_run must be boolean.
- research_packet and research_record_plan must be objects.
- Keep source_discovery/full_research discovery guardrails unchanged.
- If you use knowledge_search, web_search, finish_research,
  finish_research_from_search, evidence_item_ids_from_knowledge, or
  proposed_references_from_search, the execute_tactus call must set
  harness="research" and include assignment-aware knowledge_query_scope
  filters (assignment + note). Those helpers are unavailable in raw execute_tactus.
]], base_message, attempt, max_attempts, error_text, output_text)
        end

        local function append_recovery_trace(packet, recovery_path, retry_count, validation_failures)
            packet.researchTrace = packet.researchTrace or packet.research_trace or {}
            if type(packet.researchTrace) ~= "table" then
                packet.researchTrace = {}
            end
            packet.researchTrace.recoveryPath = recovery_path
            packet.researchTrace.retryCount = retry_count
            packet.researchTrace.validationFailures = validation_failures
            packet.research_trace = packet.researchTrace
            packet.recoveryPath = recovery_path
            packet.retryCount = retry_count
            packet.validationFailures = validation_failures
        end

        local function has_entries(value)
            return type(value) == "table" and next(value) ~= nil
        end

        local function ensure_discovery_block_reason(payload, mode_value)
            if type(payload) ~= "table" then return end
            local packet = as_table(payload.research_packet)
            if type(packet) ~= "table" then return end
            local mode = normalize_research_mode(mode_value or packet.research_mode or payload.research_mode)
            if mode == "internal_brief" then
                payload.research_packet = packet
                return
            end
            local discovery = as_table(packet.sourceDiscovery or packet.source_discovery) or {}
            local source_snapshots = discovery.sourceSnapshots or discovery.source_snapshots or packet.source_snapshots or packet.sourceSnapshots
            local proposed_references = discovery.proposedReferences or discovery.proposed_references or packet.proposed_references or packet.proposedReferences
            local web_searches = discovery.webSearches or discovery.web_searches
            if (not has_entries(web_searches)) then
                local trace = as_table(packet.researchTrace or packet.research_trace) or {}
                web_searches = trace.webSearches or trace.web_searches
            end
            discovery.webSearches = web_searches or {}
            local blocked_reason = discovery.blockedReason or discovery.blocked_reason or packet.blockedReason or packet.blocked_reason
            if (not has_entries(web_searches)) and (not has_entries(source_snapshots)) and (not has_entries(proposed_references)) then
                if type(blocked_reason) ~= "string" or blocked_reason == "" then
                    blocked_reason = "no_web_prospects_found"
                end
            end
            if type(blocked_reason) == "string" and blocked_reason ~= "" then
                discovery.blockedReason = blocked_reason
                discovery.blocked_reason = blocked_reason
                packet.blockedReason = blocked_reason
                packet.blocked_reason = blocked_reason
            end
            packet.sourceDiscovery = discovery
            packet.source_discovery = discovery
            payload.research_packet = packet
        end

        local message = string.format([[
Create an exploratory research packet for assignment %s using corpus %s.

Research mode:
%s

Research questions:
%s

Inline assignment JSON, when present:
%s

Bounded exploration:
- Maximum 6 execute_tactus calls total.
- First inspect assignment context and broad internal knowledge.
- Then optionally resolve up to 2 papyrus:// URIs or run anchored follow-up knowledge queries.
- In internal_brief mode, do not use web_search unless specifically needed to explain a blocked gap.
- In source_discovery mode, run at least one web_search after internal orientation, unless you return blockedReason.
- In full_research mode, run at least one web_search and synthesize internal findings plus external prospects, unless you return blockedReason.
- A zero-result first web_search is not terminal; rely on harness retry behavior and only treat discovery as exhausted when blockedReason is explicit.
- Keep assignment-aware knowledge orientation enabled by default (assignment and note retrieval) via the harness knowledge_search helpers.
- Finish with execute_tactus using harness="research", assignment_id=%s when no inline JSON is present, assignment_item_json when inline JSON is present, corpus_key=%s, research_mode=%s, max_evidence_items=%d, and knowledge_query_scope = { includeObjectKinds = {"reference","item","category","semanticNode","newsroomSection","assignment","message"}, includeMessageKinds = {"note"}, includeAssignmentTypeKeys = {"research.*","reporting.*"} }.
- Do not call knowledge_search, web_search, finish_research,
  finish_research_from_search, evidence_item_ids_from_knowledge, or
  proposed_references_from_search in raw execute_tactus. Those helpers are
  injected only by the research harness.

Useful raw snippets before finalization:
local context = assignment_context{ id = "%s" }
local pack = assignment_agent_context{ id = "%s", context_profile = "%s", max_tokens = 6000 }
local knowledge = knowledge_query{ query = "specific broad query", profile = "researcher", format = "both", max_tokens = 1200, top_k = 12, depth = 1 }
local object = papyrus.resolve_uri{ uri = "papyrus://reference/example" }
local anchored = knowledge_query{ uri = "papyrus://reference/example", profile = "researcher", format = "both", max_tokens = 1000, top_k = 8, depth = 1 }

Final harness snippet must use only preloaded research harness helpers:
local knowledge = knowledge_search("specific broad query", { top_k = 12, max_tokens = 1200, depth = 1 })
local evidence_ids = evidence_item_ids_from_knowledge(knowledge)
local search = nil
if "%s" ~= "internal_brief" then
    search = web_search("specific current source discovery query")
end
return finish_research{
    research_mode = "%s",
    summary = "Concise packet summary.",
    queries = {"specific broad query"},
    source_snapshots = search and search.results or {},
    proposed_references = search and proposed_references_from_search(search) or {},
    evidence_item_ids = evidence_ids,
    recommended_angle = "Specific editorial angle.",
    open_questions = {},
    coverage_gaps = {},
    researchTrace = {
        knowledgeQueries = {"specific broad query"},
        papyrusUrisInspected = {},
        webSearches = search and {"specific current source discovery query"} or {},
        acceptedEvidenceIds = evidence_ids,
        unresolvedGaps = {},
    },
}

Your final response must be exactly the structured object returned by execute_tactus.value.
It must include top-level assignment_item_id, corpus_key, dry_run, item_status,
research_packet, research_record_plan, and summary.
		]], assignment_id, corpus_key, research_mode, input.research_questions or "", assignment_json, assignment_id, corpus_key, research_mode, max_evidence_items, assignment_id, assignment_id, input.context_profile or "researcher", research_mode, research_mode)

        local validation_failures = {}
        local retry_message = message
        local first_error = nil
        local last_error = nil

        for attempt = 1, max_attempts do
            local result = newsroom_research_explorer({message = retry_message})
            local output = result.output or result
            local decoded, _ = decode_candidate(output)
            local normalized = normalize_payload(decoded)
            local errors = validate_payload(normalized)
            if #errors == 0 then
                local recovery_path = attempt > 1 and "agent_retry_success" or "agent_primary_success"
                append_recovery_trace(
                    normalized.research_packet,
                    recovery_path,
                    attempt - 1,
                    validation_failures
                )
                ensure_discovery_block_reason(normalized, research_mode)
                normalized.recovery_path = recovery_path
                normalized.retry_count = attempt - 1
                normalized.validation_failures = validation_failures
                return normalized
            end
            local failure = string.format("attempt %d: %s", attempt, table.concat(errors, "; "))
            if first_error == nil then first_error = failure end
            last_error = failure
            table.insert(validation_failures, failure)
            if attempt < max_attempts then
                retry_message = build_retry_message(message, attempt, errors, output)
            end
        end

        local fallback_query = tostring(input.research_questions or "")
        local fallback_assignment_json = assignment_json ~= "" and assignment_json or ""
        local fallback_snippet = string.format([[
local mode = %q
local requested = %q
local assignment_focus = assignment.summary or assignment.title or "the research assignment focus"
local query = requested ~= "" and requested or assignment_focus
local knowledge_ok, knowledge = pcall(knowledge_search, query, { top_k = 12, max_tokens = 1200, depth = 1 })
if (not knowledge_ok) or (type(knowledge) ~= "table") then
    knowledge = { structured = {} }
end
local evidence_ids = evidence_item_ids_from_knowledge(knowledge)
if mode == "internal_brief" then
    return finish_research{
        research_mode = mode,
        summary = "Fallback internal brief generated after structured-output retries failed.",
        recoveryPath = "procedure_fallback",
        fallbackReason = "agent_output_not_structured",
        queries = {query},
        source_snapshots = {},
        proposed_references = {},
        evidence_item_ids = evidence_ids,
        recommended_angle = "Use accepted internal evidence first, then request source discovery if needed.",
        open_questions = {},
        coverage_gaps = {},
        researchTrace = {
            knowledgeQueries = {query},
            papyrusUrisInspected = {},
            webSearches = {},
            acceptedEvidenceIds = evidence_ids,
            recoveryPath = "procedure_fallback",
            fallbackReason = "agent_output_not_structured",
            unresolvedGaps = {"agent_output_not_structured"},
        },
    }
end
local search_ok, search = pcall(web_search, query)
if (not search_ok) or (not search) then
    return finish_research{
        research_mode = mode,
        summary = "Fallback discovery packet generated with blocked web search after structured-output retries failed.",
        recoveryPath = "procedure_fallback",
        fallbackReason = "web_search_failed_after_retry",
        queries = {query},
        source_snapshots = {},
        proposed_references = {},
        evidence_item_ids = evidence_ids,
        blocked_reason = "web_search_failed_after_retry",
        recommended_angle = "Run source discovery again after validating web search availability.",
        open_questions = {"Retry discovery when web search is available."},
        coverage_gaps = {"External discovery unavailable during deterministic fallback."},
        researchTrace = {
            knowledgeQueries = {query},
            papyrusUrisInspected = {},
            webSearches = {query},
            acceptedEvidenceIds = evidence_ids,
            recoveryPath = "procedure_fallback",
            fallbackReason = "web_search_failed_after_retry",
            unresolvedGaps = {"web_search_failed_after_retry"},
        },
    }
end
return finish_research{
    research_mode = mode,
    summary = "Fallback discovery packet generated after structured-output retries failed.",
    recoveryPath = "procedure_fallback",
    fallbackReason = "agent_output_not_structured",
    queries = {query},
    source_snapshots = search.results or {},
    proposed_references = proposed_references_from_search(search),
    evidence_item_ids = evidence_ids,
    recommended_angle = "Review prospects through reference intake before using as accepted evidence.",
    open_questions = {},
    coverage_gaps = {},
    researchTrace = {
        knowledgeQueries = {query},
        papyrusUrisInspected = {},
        webSearches = {query},
        acceptedEvidenceIds = evidence_ids,
        recoveryPath = "procedure_fallback",
        fallbackReason = "agent_output_not_structured",
        unresolvedGaps = {"agent_output_not_structured"},
    },
}
]], normalize_research_mode(research_mode), fallback_query)

        local fallback_message = string.format([[
Run deterministic fallback recovery for exploratory research.

Call execute_tactus exactly once with:
- harness="research"
- assignment_id=%s (when inline assignment_json is empty)
- assignment_item_json=%s (when inline assignment_json is present)
- corpus_key=%s
- research_mode=%s
- max_evidence_items=%d
- knowledge_query_scope = { includeObjectKinds = {"reference","item","category","semanticNode","newsroomSection","assignment","message"}, includeMessageKinds = {"note"}, includeAssignmentTypeKeys = {"research.*","reporting.*"} }
- tactus snippet exactly:
%s

Return ONLY the structured execute_tactus.value object with:
assignment_item_id, corpus_key, dry_run, item_status, research_packet, research_record_plan, summary.
Do not add prose.
]], assignment_id, fallback_assignment_json, corpus_key, research_mode, max_evidence_items, fallback_snippet)

        local fallback_agent_result = newsroom_research_explorer({message = fallback_message})
        local fallback_output = fallback_agent_result.output or fallback_agent_result
        local fallback_decoded, _ = decode_candidate(fallback_output)
        local fallback_payload = normalize_payload(fallback_decoded)
        local fallback_errors = validate_payload(fallback_payload)
        if #fallback_errors > 0 then
            local mode = normalize_research_mode(research_mode)
            local query = fallback_query ~= "" and fallback_query or "the research assignment focus"
            local fallback_packet = {
                research_mode = mode,
                summary = "Deterministic fallback research packet generated after agent output could not be structured.",
                recoveryPath = "procedure_fallback",
                fallbackReason = "agent_output_not_structured",
                queries = {query},
                source_snapshots = {},
                proposed_references = {},
                evidence_item_ids = {},
                recommended_angle = "Retry the research agent or run source discovery again before using this packet as evidence.",
                open_questions = {"What accepted evidence and source prospects should replace this fallback packet?"},
                coverage_gaps = {"Agent output was not structured enough to create a grounded research packet."},
                researchTrace = {
                    knowledgeQueries = {query},
                    papyrusUrisInspected = {},
                    webSearches = {},
                    acceptedEvidenceIds = {},
                    recoveryPath = "procedure_fallback",
                    fallbackReason = "agent_output_not_structured",
                    unresolvedGaps = {"agent_output_not_structured"},
                },
            }
            if mode ~= "internal_brief" then
                fallback_packet.blockedReason = "agent_output_not_structured"
                table.insert(fallback_packet.open_questions, "Can source discovery be retried with a structured final response?")
                table.insert(fallback_packet.coverage_gaps, "External discovery did not produce a structured source prospect list.")
            end
            append_recovery_trace(
                fallback_packet,
                "procedure_fallback",
                max_attempts,
                validation_failures
            )
            local fallback_response = {
                assignment_item_id = assignment_id ~= "" and assignment_id or "assignment-unknown",
                corpus_key = corpus_key,
                dry_run = true,
                item_status = "researched",
                research_packet = fallback_packet,
                research_record_plan = {
                    dryRun = true,
                    lifecycle = "assignment-research-packet",
                    records = {},
                    warnings = {
                        string.format(
                            "fallback agent output invalid: first_error=%s last_error=%s fallback_error=%s",
                            first_error or "none",
                            last_error or "none",
                            table.concat(fallback_errors, "; ")
                        )
                    },
                },
                summary = fallback_packet.summary,
                recovery_path = "procedure_fallback",
                retry_count = max_attempts,
                validation_failures = validation_failures,
            }
            ensure_discovery_block_reason(fallback_response, research_mode)
            return fallback_response
        end
        append_recovery_trace(
            fallback_payload.research_packet,
            "procedure_fallback",
            max_attempts,
            validation_failures
        )
        ensure_discovery_block_reason(fallback_payload, research_mode)
        if type(fallback_payload.summary) ~= "string" or fallback_payload.summary == "" then
            fallback_payload.summary = "Created dry-run exploratory research packet via deterministic fallback."
        end
        if type(fallback_payload.item_status) ~= "string" or fallback_payload.item_status == "" then
            fallback_payload.item_status = "researched"
        end
        if type(fallback_payload.dry_run) ~= "boolean" then
            fallback_payload.dry_run = true
        end
        if type(fallback_payload.assignment_item_id) ~= "string" or fallback_payload.assignment_item_id == "" then
            fallback_payload.assignment_item_id = assignment_id ~= "" and assignment_id or "assignment-unknown"
        end
        if type(fallback_payload.corpus_key) ~= "string" or fallback_payload.corpus_key == "" then
            fallback_payload.corpus_key = corpus_key
        end
        if type(fallback_payload.research_record_plan) ~= "table" then
            fallback_payload.research_record_plan = {}
        end
        if type(fallback_payload.research_packet) ~= "table" then
            fallback_payload.research_packet = {}
            append_recovery_trace(
                fallback_payload.research_packet,
                "procedure_fallback",
                max_attempts,
                validation_failures
            )
        end
        return {
            assignment_item_id = fallback_payload.assignment_item_id,
            corpus_key = fallback_payload.corpus_key,
            dry_run = fallback_payload.dry_run,
            item_status = fallback_payload.item_status,
            research_packet = fallback_payload.research_packet,
            research_record_plan = fallback_payload.research_record_plan,
            summary = fallback_payload.summary,
            recovery_path = "procedure_fallback",
            retry_count = max_attempts,
            validation_failures = validation_failures,
        }
    end
}

Specification([[
Feature: Knowledge-aware exploratory researcher procedure
  The researcher can inspect internal knowledge, resolve Papyrus URIs, search the web, and finish with a Message-backed packet.

  Scenario: Explorer returns a live assignment research packet plan
    Given the procedure has started
    And the input assignment_item_id is "assignment-live-123"
    And the input corpus_key is "AI-ML-research"
    And the input context_profile is "researcher"
    And the input max_evidence_items is 2
    And the input research_questions is "Find gaps around production agent evaluation."
    And the agent "newsroom_research_explorer" calls tool "execute_tactus" with args {"tactus": "local context = assignment_context{ id = \"assignment-live-123\" }; local pack = assignment_agent_context{ id = \"assignment-live-123\", context_profile = \"researcher\", max_tokens = 6000 }; return { context = context, pack = pack }"}
    And the agent "newsroom_research_explorer" calls tool "execute_tactus" with args {"tactus": "return knowledge_query{ query = \"production agent evaluation\", profile = \"researcher\", format = \"both\", max_tokens = 1200, top_k = 12, depth = 1 }"}
    And the agent "newsroom_research_explorer" calls tool "execute_tactus" with args {"tactus": "return papyrus.resolve_uri{ uri = \"papyrus://reference/reference-1\" }"}
    And the agent "newsroom_research_explorer" calls tool "execute_tactus" with args {"tactus": "return papyrus.reference.web_search{ query = \"production AI agent evaluation 2026\", model = \"gpt-5.4-mini\", max_results = 2 }"}
    And the agent "newsroom_research_explorer" calls tool "execute_tactus" with args {"harness":"research","assignment_id":"assignment-live-123","corpus_key":"AI-ML-research","research_mode":"source_discovery","max_evidence_items":2,"tactus":"local knowledge = knowledge_search(\"production agent evaluation\", { top_k = 12, max_tokens = 1200 }); local ids = evidence_item_ids_from_knowledge(knowledge); return finish_research{ research_mode = \"source_discovery\", summary = \"Internal evidence plus web prospects identified.\", queries = {\"production agent evaluation\"}, source_snapshots = {{ title = \"Production AI agent evaluation 2026\", url = \"https://example.com/report\" }}, proposed_references = {{ title = \"Production AI agent evaluation 2026\", url = \"https://example.com/report\", ingestion_rationale = \"Current external prospect for the assignment focus.\" }}, evidence_item_ids = ids, recommended_angle = \"Compare operational evaluation methods.\", researchTrace = { knowledgeQueries = {\"production agent evaluation\"}, papyrusUrisInspected = {\"papyrus://reference/reference-1\"}, webSearches = {\"production AI agent evaluation 2026\"}, acceptedEvidenceIds = ids, unresolvedGaps = {} } }"}
    And the agent "newsroom_research_explorer" returns data {"assignment_item_id":"assignment-live-123","corpus_key":"AI-ML-research","dry_run":True,"item_status":"researched","research_packet":{"research_mode":"source_discovery","summary":"Internal evidence plus web prospects identified.","sourceSnapshots":[{"title":"Production AI agent evaluation 2026","url":"https://example.com/report"}],"proposedReferences":[{"title":"Production AI agent evaluation 2026","url":"https://example.com/report","ingestion_rationale":"Current external prospect for the assignment focus."}],"researchTrace":{"knowledgeQueries":["production agent evaluation"],"papyrusUrisInspected":["papyrus://reference/reference-1"],"webSearches":["production AI agent evaluation 2026"],"acceptedEvidenceIds":["reference-1-v1"],"unresolvedGaps":[]}},"research_record_plan":{"dryRun":True,"lifecycle":"assignment-research-packet","records":[{"modelName":"Message","action":"create"}]},"summary":"Created dry-run exploratory research packet."}
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output research_packet should exist
    And the output research_record_plan should exist

  Scenario: Explorer retries after malformed first response
    Given the procedure has started
    And the input assignment_item_id is "assignment-live-456"
    And the input corpus_key is "AI-ML-research"
    And the input research_mode is "source_discovery"
    And the input research_questions is "Find model-zoo workflow sources."
    And the agent "newsroom_research_explorer" returns data {"note":"not structured"}
    And the agent "newsroom_research_explorer" returns data {"assignment_item_id":"assignment-live-456","corpus_key":"AI-ML-research","dry_run":True,"item_status":"researched","research_packet":{"research_mode":"source_discovery","summary":"Retry success packet.","source_snapshots":[{"title":"Model Zoo Workflow","url":"https://example.com/model-zoo-workflow"}],"proposed_references":[{"title":"Model Zoo Workflow","url":"https://example.com/model-zoo-workflow","ingestion_rationale":"External reference prospect for assignment focus."}],"researchTrace":{"webSearches":["model zoo workflow automation"],"acceptedEvidenceIds":[]}},"research_record_plan":{"dryRun":True,"lifecycle":"assignment-research-packet","records":[{"modelName":"Message","action":"create"}]},"summary":"Retry success packet."}
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output research_packet should exist
    And the output summary should be Retry success packet.

  Scenario: Explorer extracts trailing JSON object from prose output
    Given the procedure has started
    And the input assignment_item_id is "assignment-live-789"
    And the input corpus_key is "AI-ML-research"
    And the input research_mode is "source_discovery"
    And the agent "newsroom_research_explorer" returns data "model note before object {\"assignment_item_id\":\"assignment-live-789\",\"corpus_key\":\"AI-ML-research\",\"dry_run\":true,\"item_status\":\"researched\",\"research_packet\":{\"research_mode\":\"source_discovery\",\"summary\":\"Trailing object parsed.\",\"source_snapshots\":[{\"title\":\"External candidate\",\"url\":\"https://example.com/external-candidate\"}],\"proposed_references\":[{\"title\":\"External candidate\",\"url\":\"https://example.com/external-candidate\",\"ingestion_rationale\":\"Prospect for reference intake.\"}],\"researchTrace\":{\"webSearches\":[\"external candidate search\"],\"acceptedEvidenceIds\":[]}},\"research_record_plan\":{\"dryRun\":true,\"lifecycle\":\"assignment-research-packet\",\"records\":[{\"modelName\":\"Message\",\"action\":\"create\"}]},\"summary\":\"Trailing object parsed.\"}"
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output summary should be Trailing object parsed.

  Scenario: Explorer uses deterministic fallback after repeated invalid output
    Given the procedure has started
    And the input assignment_item_id is "assignment-live-fallback-1"
    And the input assignment_json is "{\"id\":\"assignment-live-fallback-1\",\"assignmentTypeKey\":\"research.edition-candidate\",\"queueKey\":\"research#open\",\"queueStatusKey\":\"research#open#open\",\"status\":\"open\",\"title\":\"Fallback assignment\"}"
    And the input corpus_key is "AI-ML-research"
    And the input research_mode is "internal_brief"
    And the agent "newsroom_research_explorer" returns data {"invalid":"attempt-1"}
    And the agent "newsroom_research_explorer" returns data {"invalid":"attempt-2"}
    And the agent "newsroom_research_explorer" returns data {"invalid":"attempt-3"}
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output research_packet should exist
    And the output summary should exist
]])
