-- Papyrus reference summarization procedure.
--
-- Shared operator-editable prompt surface for reference summary generation:
-- - reference_summary mode (Message relation summaries)
-- - outcome_summary mode (title/subtitle enrichment summaries)
--
-- This procedure is prompt-only style guidance. It does not enforce hard
-- rejection/regeneration rules for phrasing.

newsroom_reference_summarizer = Agent {
    provider = "openai",
    model = "gpt-6-luna",
    system_prompt = [[
You summarize reference source material for Papyrus editorial curation metadata.

Always write in source voice:
- State what the source says directly.
- Do not frame as commentary about the source.
- Avoid openings like "This paper/article/review/work/study..." or "In this paper...".
- Do not describe the document itself ("A systematic review examines...", "The study investigates...", "The paper argues...").
- You may mention substantive evidence/method terms (survey, poll, trial, study, experiment) when they are part of the finding itself.
- Write claims directly (example: "Intelligent assessment and generative AI can strengthen learner agency when used as support, but can weaken it when over-relied on.").

Grounding rules:
- Keep claims faithful to provided source text and metadata.
- Do not invent evidence, citations, findings, or recommendations.
- Be concise and useful for downstream newsroom context.
]],
    output = {
        summary_text = field.string{required = true}
    }
}

Procedure {
    input = {
        mode = field.string{required = true, description = "reference_summary or outcome_summary"},
        source_text = field.string{required = true, description = "Source text content"},
        max_tokens = field.number{default = 1800, description = "Target summary token budget"},
        reference_title = field.string{default = "", description = "Reference title"},
        source_uri = field.string{default = "", description = "Reference source URI"},
        known_title = field.string{default = "", description = "Resolved title for outcome mode"},
        known_subtitle = field.string{default = "", description = "Resolved subtitle for outcome mode"},
        media_type = field.string{default = "", description = "Reference media type"},
        doctrine_context_text = field.string{default = "", description = "Publication doctrine block for reference_summary mode"},
        model = field.string{default = "gpt-6-luna", description = "Model hint for metadata only"},
        prompt_version = field.string{default = "", description = "Optional override prompt version"}
    },
    output = {
        mode = field.string{required = true},
        summary_text = field.string{required = true},
        prompt_version = field.string{required = true},
        model = field.string{required = false}
    },
    function(input)
        local mode = input.mode or ""
        local budget = tonumber(input.max_tokens) or 1800
        if budget < 100 then
            budget = 100
        end
        local reference_title = input.reference_title or ""
        local source_uri = input.source_uri or ""
        local source_text = input.source_text or ""
        local doctrine_block = input.doctrine_context_text or ""
        local known_title = input.known_title or ""
        local known_subtitle = input.known_subtitle or ""
        local media_type = input.media_type or ""
        local model = input.model or "gpt-6-luna"

        local prompt_version = input.prompt_version or ""
        local message = ""

        if mode == "reference_summary" then
            if prompt_version == "" then
                prompt_version = "reference-summary-v3-source-voice"
            end
            message = string.format([[
Write a concise summary in no more than %d tokens.

State what the source says directly in source voice.
Do not use referential lead-ins such as:
- "This paper..."
- "This article..."
- "This review..."
- "This work..."
- "This study..."
- "In this paper..."
- "A systematic review examines..."
- "The study investigates..."
- "The paper argues..."
You may mention substantive evidence/method terms (survey, poll, trial, study, experiment) when they are part of the finding itself.

Preserve the central contribution, method, evidence type, and relevance.
Do not add claims that are not supported by the provided text.

Publication Context:
%s

Important policy-use rule: Editorial policies describe standards for downstream
published Papyrus content. They are included only as publication context for
this Reference summary and should not be treated as rules that the Reference itself must satisfy.

Title: %s
Source URI: %s

%s
]], budget, doctrine_block, reference_title, source_uri, source_text)
        elseif mode == "outcome_summary" then
            if prompt_version == "" then
                prompt_version = "reference-title-subtitle-summary-v2-source-voice"
            end
            message = string.format([[
Write an outcome-focused summary in no more than %d tokens.

State what the source is saying directly in source voice.
Do not use referential lead-ins such as:
- "This paper..."
- "This article..."
- "This review..."
- "This work..."
- "This study..."
- "In this paper..."
- "A systematic review examines..."
- "The study investigates..."
- "The paper argues..."
You may mention substantive evidence/method terms (survey, poll, trial, study, experiment) when they are part of the finding itself.

Explain findings, conclusions, outcomes, recommendations, or the central
message. Keep claims grounded in the source text.
Bullet points are allowed only after an opening explanatory paragraph.
Do not start with bullets.

Known title: %s
Known subtitle: %s
Reference media type: %s
Source URI: %s

%s
]], budget, known_title, known_subtitle, media_type, source_uri, source_text)
        else
            error("Unsupported mode for newsroom.reference.summarization: " .. tostring(mode))
        end

        message = message .. "\n\nReturn strict JSON with one key: summary_text."
        local result = newsroom_reference_summarizer({message = message})
        local summary_text = result.output.summary_text or ""
        return {
            mode = mode,
            summary_text = summary_text,
            prompt_version = prompt_version,
            model = model
        }
    end
}
