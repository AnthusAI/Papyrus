-- Papyrus ontology relationship explainer procedure.
--
-- Generates source-specific meaning for one SemanticRelation. Persistence is
-- owned by the outer Papyrus ontology CLI, which stores the output as a
-- SemanticRelation ModelAttachment and audit Message.

local json = require("tactus.io.json")

ontology_relationship_explainer = Agent {
    provider = "openai",
    model = "gpt-6-luna",
    system_prompt = [[
You explain ontology relationships for Papyrus.

Goal:
- Explain what one SemanticRelation means in the context of its subject, object,
  surrounding graph, available source metadata, Messages, and attachments.
- Keep the explanation grounded in the supplied context only.
- Treat the explanation as contextual, not universal truth.

Rules:
- Return strict structured data only.
- Do not invent source text, citations, identifiers, or evidence spans.
- Use concise source-facing language useful for retrieval and future concept
  profiling.
- Confidence should reflect contextual support, not whether the relation exists.
- Candidate associations must be additive suggestions only.
]],
    output = {
        relation_explanation = field.object{required = true}
    }
}

Procedure {
    input = {
        context_json = field.object{required = true, description = "Ontology relation context JSON from Papyrus CLI"}
    },
    output = {
        relation_explanation = field.object{required = true}
    },
    function(input)
        local function safe_get(table_like, key)
            if type(table_like) ~= "table" then
                return nil
            end
            local ok, value = pcall(function()
                return table_like[key]
            end)
            if ok then
                return value
            end
            return nil
        end

        local function normalize_table(value)
            if type(value) == "table" then
                return value
            end
            return {}
        end

        local function normalize_number(value, default_value)
            local as_number = tonumber(value)
            if as_number == nil then
                return default_value
            end
            return as_number
        end

        local context = input.context_json
        local message = string.format([[
Explain this Papyrus ontology relation from the supplied JSON context.

Required JSON shape for relation_explanation:
{
  "meaning": "1-3 sentence contextual explanation",
  "evidence": [{"source":"field/message/attachment/relation", "text":"short evidence note", "objectId":"optional"}],
  "ambiguity": ["short caveat"],
  "confidence": 0.0,
  "candidateAssociations": [{"predicate":"related_to", "targetConceptId":"semantic-node-id", "confidence":0.0, "rationale":"short reason"}],
  "model": "gpt-6-luna"
}

Context JSON:
%s
]], json.encode(context))
        local result = ontology_relationship_explainer({message = message})
        local output = safe_get(result, "output")
        local explanation = safe_get(output, "relation_explanation")
        if type(explanation) ~= "table" then
            explanation = safe_get(output, "relationExplanation")
        end
        if type(explanation) ~= "table" then
            explanation = safe_get(result, "relation_explanation")
        end
        if type(explanation) ~= "table" then
            explanation = safe_get(result, "relationExplanation")
        end
        if type(explanation) ~= "table" and type(output) == "table" and safe_get(output, "meaning") ~= nil then
            explanation = output
        end
        if type(explanation) ~= "table" and type(result) == "table" and safe_get(result, "meaning") ~= nil then
            explanation = result
        end
        explanation = normalize_table(explanation)
        explanation.meaning = tostring(explanation.meaning or "No contextual explanation was generated.")
        explanation.evidence = normalize_table(explanation.evidence)
        explanation.ambiguity = normalize_table(explanation.ambiguity)
        explanation.candidateAssociations = normalize_table(explanation.candidateAssociations)
        explanation.confidence = normalize_number(explanation.confidence, 0.0)
        explanation.model = tostring(explanation.model or "gpt-6-luna")
        return {
            relation_explanation = explanation
        }
    end
}

Specification([[
Feature: Ontology relationship explanation
  The procedure explains one SemanticRelation from supplied Papyrus context.

  Scenario: Relationship explainer returns a contextual meaning object
    Given the procedure has started
    And the input context_json is {"relation":{"id":"semantic-relation-1","predicate":"mentions"},"subject":{"record":{"title":"Reference"}},"object":{"record":{"displayName":"Concept"}}}
    And the agent "ontology_relationship_explainer" returns data {"relation_explanation":{"meaning":"Reference mentions Concept in context.","evidence":[],"ambiguity":[],"confidence":0.9,"candidateAssociations":[],"model":"gpt-6-luna"}}
    When the procedure runs
    Then the procedure should complete successfully
    And the output relation_explanation should exist
]])
