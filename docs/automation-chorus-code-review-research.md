# Automation: Chorus code review research dispatch

Registers [Chorus](https://chorus.codes) as a pending knowledge-base reference, then
starts two `research.tavily-deep` assignments:

1. **Technology desk** — open-source and local-first tools comparable to Chorus
2. **Science desk** — academic papers on multi-model / LLM code review

## Required automation secrets

Configure these in the Cursor automation secret list (in addition to
`OPENAI_API_KEY`):

| Secret | Purpose |
| --- | --- |
| `PAPYRUS_JWT_SECRET` | Mint short-lived `PAPYRUS_GRAPHQL_JWT` without AWS CLI |
| `TAVILY_API_KEY` | Tavily deep research API (`research.tavily-deep`) |
| `PAPYRUS_GRAPHQL_ENDPOINT` | Optional; defaults to production AppSync URL |

Alternatively provide `PAPYRUS_GRAPHQL_JWT` directly, or
`AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_REGION` for SSM JWT minting.

## Command

```bash
./scripts/dispatch-chorus-code-review-research.sh
```

Dry-run (no GraphQL or Tavily calls):

```bash
./scripts/dispatch-chorus-code-review-research.sh --dry-run
```

Partial runs:

```bash
./scripts/dispatch-chorus-code-review-research.sh --skip-academic
./scripts/dispatch-chorus-code-review-research.sh --skip-tools --skip-reference
```

## Manual equivalents

```bash
# Reference
poetry run papyrus references make-catalog --input chorus-source.txt --output chorus-catalog.json
poetry run papyrus references prepare-catalog --config corpora/papyrus-steering.yml \
  --corpus-key AI-ML-research --catalog chorus-catalog.json --output chorus-prepared.json
poetry run papyrus references create-from-catalog --config corpora/papyrus-steering.yml \
  --corpus-key AI-ML-research --catalog chorus-prepared.json --status pending \
  --ingestion-rationale "<rationale>"

# Tavily deep research
poetry run papyrus assignments create-research --type research.tavily-deep \
  --title "Open-source multi-model code review tools (Chorus landscape)" \
  --section technology --corpus-key AI-ML-research --instructions "<query>" --apply
poetry run papyrus assignments run-tavily-deep-research --assignment <id> --wait
```
