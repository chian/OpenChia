"""Lexical-probe Episode, including its complete chunk-extraction Leaf."""

from handoff_library import ADMIT_PARENT_REQUEST, HandoffPayloadContract
from llm_call_library import ModelTier, STRUCTURED_JSON_COMPLETION
from method_loop import (
    EpisodeBindingDeclaration,
    EpisodeControllerBinding,
    EpisodeTopologyRole,
)
from numeric_control_library import (
    COMPOSE_INCIDENCE_CONTROLLER,
    MARGINAL_DOMINATED_HYPERVOLUME,
    PAIRED_INCIDENCE,
    PREDICTED_CREDIT_UPPER_BOUND,
)
from question_table_goal_library import (
    PROJECT_ACCEPTED_IDENTITY_CHANNELS,
    PROJECT_DIRECT_EVIDENCE_CANDIDATES,
    PROJECT_GOAL_PROMPT,
    PROPOSE_TABLE_RESULTS,
    RESULT_COLUMN_SCHEMA,
    SCOPE_QUESTION_TABLE_GOAL,
)

from .models import EpisodeLibraryDesign
from .provenance import source_function, source_symbol


_LEXICAL_PATH = "question_pipeline/episode_binding/lexical_probe_binding.py"
_CHUNK_PATH = "question_pipeline/episode_binding/chunk_binding.py"
_PAGE_PATH = "question_pipeline/episode_binding/page_binding.py"
_PROVIDER_PATH = "question_pipeline/episode_binding/provider_binding.py"
_EXTRACTION_PATH = "question_pipeline/utilities/extraction.py"

UNCERTAINTY_ALPHA = 0.05
STOP_WHEN_PREDICTED_CREDIT_UPPER_AT_MOST = 0.01

REQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract(
    artifact_roles=("goal_scope", "unit"),
    required_artifact_roles=("goal_scope", "unit"),
)
RESULT_PAYLOAD_CONTRACT = HandoffPayloadContract()

CHUNK_EXTRACTION_SYSTEM_PROMPT = (
    "Extract exact source-grounded rows for the supplied declared table contract. "
    "Return one JSON object and make no acquisition or stopping decision."
)

CHUNK_EXTRACTION_PROMPT = """TABLE CONTRACT:
{goal_contract_json}

SOURCE CHUNK:
{source_chunk}

Extract every distinct source-local subject described in this chunk that
belongs in a declared table.

Rules:
- Return only declared table and column names.
- Return only reported columns. Best-guess columns are handled by a separate
  evidence-anchored reasoning step.
- One row represents one subject at the table's declared grain.
- Partial rows are allowed, but include every explicitly stated subject-key
  column. Never invent a missing identity field.
- Every string value must be an exact substring of SOURCE CHUNK.
- Never combine facts from different subjects.
- If the chunk contains no qualifying row, return an empty rows list.

Return exactly:
{{
  "rows": [
    {{
      "table": "declared_table_name",
      "values": {{"declared_reported_column": "exact source value"}}
    }}
  ]
}}"""


RANK_CHUNKS = source_function(
    function_id="rank_lexical_chunks",
    interface="retrieval.lexical_ranking",
    description="Rank the remaining page chunks against one literal probe query.",
    input_type="unprocessed chunk spans and literal query",
    output_type="ordered chunk spans",
    sources=((_EXTRACTION_PATH, "rank_chunks"),),
    effect="Pure deterministic lexical ranking over already acquired text.",
    failure_contract="Never creates, merges, or consumes a chunk during ranking.",
)

RANKED_CHUNK_SOURCE = source_function(
    function_id="ranked_chunk_source",
    interface="episode.unit_source",
    description="Pull one ranked chunk that has not been processed by any probe.",
    input_type="Page state and ranked chunk sequence",
    output_type="complete chunk Leaf or source exhaustion",
    sources=(
        (_LEXICAL_PATH, "RankedChunkSource"),
        (_CHUNK_PATH, "ChunkBinding._make_chunk_leaf"),
    ),
    effect="Makes the chunk Leaf the unit of the lexical-probe Episode.",
    failure_contract="A chunk can be consumed only once across Page probes.",
)

ADMIT_CHUNK_EXTRACTION = source_function(
    function_id="admit_chunk_extraction",
    interface="llm.response_admission",
    description="Admit only declared reported columns and exact source substrings.",
    input_type="structured JSON model response, source chunk, and table contract",
    output_type="validated table rows",
    sources=((_EXTRACTION_PATH, "TableSpecExtractor._validated_rows"),),
    effect="Pure semantic and substring validation.",
    failure_contract="Malformed or invented values produce no accepted row.",
)

ACCEPT_CHUNK_EVIDENCE = source_function(
    function_id="accept_chunk_evidence",
    interface="evidence.acceptance",
    description="Commit the exact chunk and candidate assertions before Goal preview.",
    input_type="chunk unit and validated extracted rows",
    output_type="evidence commit and record artifact IDs",
    sources=((_PAGE_PATH, "PageBinding.accept_evidence"),),
    effect="Uses the durable evidence registry as the acceptance boundary.",
    failure_contract="A row without a complete accepted source chain mints no identity.",
)

BUILD_LEXICAL_PROBE_RESULT = source_function(
    function_id="build_lexical_probe_result",
    interface="handoff.child_result_builder",
    description="Build one closed lexical-probe result for its parent Page.",
    input_type="completed probe state and matching ParentRequest",
    output_type="handoff_library.ChildResult",
    sources=(
        (_CHUNK_PATH, "ChunkBinding._chunk_result"),
        (_LEXICAL_PATH, "LexicalProbeBinding._on_chunk"),
        (_PROVIDER_PATH, "ProviderRuntime._episode_result"),
    ),
    effect="Returns identities by channel, measurements, flags, and artifact IDs.",
    failure_contract="Never returns source chunk text or model output upward.",
)


BINDING = EpisodeBindingDeclaration(
    grain_name="lexical_probe",
    interface="question_pipeline.lexical_probe",
    topology_role=EpisodeTopologyRole.LEAF,
    goal="one lexical probe proposal within its Page Goal",
    unit="one ranked, previously unprocessed chunk Leaf",
    result="accepted chunk evidence projected to stable table identities",
    progress=(
        "marginal dominated hypervolume over accepted stable identities kept "
        "distinct by declared result channel"
    ),
    stopping=(
        "continue while the upper uncertainty bound on predicted next marginal "
        "hypervolume exceeds the declared tolerance"
    ),
    admit_request=ADMIT_PARENT_REQUEST.bind(
        "admit_lexical_probe_request",
        arguments={"payload_contract": REQUEST_PAYLOAD_CONTRACT.as_record()},
    ),
    open_source=RANKED_CHUNK_SOURCE.bind("open_ranked_chunk_source"),
    controller=EpisodeControllerBinding(
        schema=RESULT_COLUMN_SCHEMA.bind("result_column_schema"),
        composer=COMPOSE_INCIDENCE_CONTROLLER.bind("compose_controller"),
        credit=MARGINAL_DOMINATED_HYPERVOLUME.bind("assign_credit"),
        rarefaction=PAIRED_INCIDENCE.bind(
            "estimate_future_yield",
            arguments={"uncertainty_alpha": UNCERTAINTY_ALPHA},
        ),
        continuation=PREDICTED_CREDIT_UPPER_BOUND.bind(
            "decide_continuation",
            arguments={
                "max_predicted_marginal_hypervolume": (
                    STOP_WHEN_PREDICTED_CREDIT_UPPER_AT_MOST
                )
            },
        ),
    ),
    build_result=BUILD_LEXICAL_PROBE_RESULT.bind(
        "build_lexical_probe_result",
        arguments={"payload_contract": RESULT_PAYLOAD_CONTRACT.as_record()},
    ),
    components=(
        SCOPE_QUESTION_TABLE_GOAL.bind("scope_goal"),
        PROJECT_GOAL_PROMPT.bind("project_goal_prompt"),
        RANK_CHUNKS.bind("rank_chunks"),
        STRUCTURED_JSON_COMPLETION.bind(
            "extract_chunk",
            arguments={
                "tier": ModelTier.REASONING.value,
                "system_prompt": CHUNK_EXTRACTION_SYSTEM_PROMPT,
                "prompt_template": CHUNK_EXTRACTION_PROMPT,
            },
        ),
        ADMIT_CHUNK_EXTRACTION.bind("admit_chunk_extraction"),
        ACCEPT_CHUNK_EVIDENCE.bind("accept_evidence"),
        PROJECT_DIRECT_EVIDENCE_CANDIDATES.bind("project_direct_candidates"),
        PROPOSE_TABLE_RESULTS.bind("propose_table_results"),
        PROJECT_ACCEPTED_IDENTITY_CHANNELS.bind("project_accepted_identities"),
    ),
)

DESIGN = EpisodeLibraryDesign(
    qualified_name="question_pipeline.lexical_probe",
    title="Lexical probe with chunk Leaf",
    binding=BINDING,
    function_definitions=(
        ADMIT_PARENT_REQUEST,
        RANKED_CHUNK_SOURCE,
        RESULT_COLUMN_SCHEMA,
        COMPOSE_INCIDENCE_CONTROLLER,
        MARGINAL_DOMINATED_HYPERVOLUME,
        PAIRED_INCIDENCE,
        PREDICTED_CREDIT_UPPER_BOUND,
        BUILD_LEXICAL_PROBE_RESULT,
        SCOPE_QUESTION_TABLE_GOAL,
        PROJECT_GOAL_PROMPT,
        RANK_CHUNKS,
        STRUCTURED_JSON_COMPLETION,
        ADMIT_CHUNK_EXTRACTION,
        ACCEPT_CHUNK_EVIDENCE,
        PROJECT_DIRECT_EVIDENCE_CANDIDATES,
        PROPOSE_TABLE_RESULTS,
        PROJECT_ACCEPTED_IDENTITY_CHANNELS,
    ),
    source_symbols=(
        source_symbol(_LEXICAL_PATH, "LexicalProbeBinding"),
        source_symbol(_LEXICAL_PATH, "RankedChunkSource"),
        source_symbol(_CHUNK_PATH, "ChunkBinding"),
        source_symbol(_CHUNK_PATH, "ChunkResult"),
    ),
)


__all__ = [
    "BINDING",
    "CHUNK_EXTRACTION_PROMPT",
    "CHUNK_EXTRACTION_SYSTEM_PROMPT",
    "DESIGN",
    "REQUEST_PAYLOAD_CONTRACT",
    "RESULT_PAYLOAD_CONTRACT",
]
