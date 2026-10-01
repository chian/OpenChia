"""Source-table Episode: interpret one detected table, then query its entities."""

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


_BINDING_PATH = "question_pipeline/episode_binding/source_table_binding.py"
_PROVIDER_PATH = "question_pipeline/episode_binding/provider_binding.py"

UNCERTAINTY_ALPHA = 0.05
STOP_WHEN_PREDICTED_CREDIT_UPPER_AT_MOST = 0.01

REQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract(
    artifact_roles=("goal_scope", "unit"),
    required_artifact_roles=("goal_scope", "unit"),
)
RESULT_PAYLOAD_CONTRACT = HandoffPayloadContract()

PROGRAM_SYSTEM_PROMPT = (
    "You write validated programs in the supplied table language. Return one "
    "JSON object. You may judge semantic relevance and source meaning, but "
    "never decide whether acquisition continues."
)

PROGRAM_PROMPT = """DECLARED TARGET ENTITIES:
{target_contract_json}

SOURCE TABLE WORKSPACE:
{workspace_json}

TABLE LANGUAGE:
{language_reference_json}

Decide whether this source table contains entities for one declared target. If
it does, write a table-language program. Map source columns to semantic fields,
not directly to storage columns. Use source context for headings, legends,
units, scopes, and footnotes. A satisfy command is valid only when its cited
span directly establishes a declared admission rule for its scope. Never
invent cell values or alter the declared target or rules. If this table does
not represent a declared target, return a skip decision.

Return either:
{{"decision": "skip", "reason": "brief source-grounded reason"}}

or:
{{
  "decision": "map",
  "target_entity": "declared target name",
  "commands": [
    {{"op": "parse", "parser_kind": "markdown", "data_start_row": 1, "header_rows": [0]}},
    {{"op": "entries", "mode": "one_per_row", "identity_source_columns": [0]}},
    {{"op": "map_column", "source_column": 0, "target_field": "semantic_field", "parse_as": "text"}},
    {{"op": "emit"}}
  ],
  "rationale": "brief explanation of the source layout and context"
}}"""

COMMUNITY_SYSTEM_PROMPT = (
    "You resolve candidate source mentions into entity communities. Return one "
    "JSON object and make no acquisition or stopping decision."
)

COMMUNITY_PROMPT = """SOURCE-GROUNDED MENTIONS:
{mentions_json}

Partition every presented mention into real-world entities. Combine mentions
only when they refer to the same underlying entity, including different
spelling, formatting, precision, or wording. Use mutually consistent fields
and source context together; candidate connections are hints, not limits.
Complementary fields may be combined. Conflicting identity or event facts mean
the mentions stay separate. Return every presented mention id exactly once.
Never create ids, values, or fields.

Return exactly:
{{"communities": [["mention_id", "mention_id"], ["mention_id"]]}}"""

QUERY_SYSTEM_PROMPT = (
    "You propose one deterministic query over an already interpreted source "
    "table. Return one JSON object. Never decide whether to continue."
)

QUERY_PROMPT = """QUESTION:
{question}

DECLARED TABLE CONTRACT:
{goal_contract_json}

PARSED SOURCE TABLE:
{dataset_summary_json}

CURRENT TABLE-FILL STATE:
{goal_state_json}

PREVIOUS QUERIES AND MEASURED RESULTS:
{previous_queries_json}

Propose one query over the remaining admitted entities. Use previous measured
yields to target useful entities earlier queries missed. required_columns
keeps entities where those projected columns are non-empty. contains performs
case-insensitive literal matching within a projected column. Empty filters
select all remaining entities. You propose the query only; numerical control
decides whether another query will be attempted.

Return exactly:
{{
  "required_columns": ["projected result column"],
  "contains": [{{"column": "projected result column", "text": "literal text"}}],
  "rationale": "brief strategy based on prior outcomes"
}}"""


SOURCE_TABLE_QUERY_SOURCE = source_function(
    function_id="source_table_query_source",
    interface="episode.unit_source",
    description="Interpret the table once, then pull one query over remaining rows.",
    input_type="source-table state and Episode view",
    output_type="SourceTableQueryUnit or source exhaustion",
    sources=((_BINDING_PATH, "SourceTableQuerySource"),),
    effect="Maintains processed row IDs and measured query history.",
    failure_contract="Never treats an invalid program or query as an observed unit.",
)

ADMIT_TABLE_PROGRAM = source_function(
    function_id="admit_source_table_program",
    interface="llm.response_admission",
    description="Validate a skip or program against targets, spans, and table language.",
    input_type="structured JSON response and source-table workspace",
    output_type="SourceTableDataset",
    sources=((_BINDING_PATH, "interpret_source_table_region"),),
    effect="Executes only validated commands over exact source spans.",
    failure_contract="Rejects undeclared targets, spans, commands, and semantic fields.",
)

ADMIT_MENTION_COMMUNITIES = source_function(
    function_id="admit_mention_communities",
    interface="llm.response_admission",
    description="Validate an exact partition of the supplied mention IDs.",
    input_type="structured JSON response and LanguageResult",
    output_type="resolved LanguageResult",
    sources=((_BINDING_PATH, "_resolve_candidate_mentions"),),
    effect="Applies no value or field absent from the source-grounded mentions.",
    failure_contract="Rejects missing, repeated, or invented mention IDs.",
)

ADMIT_SOURCE_TABLE_QUERY = source_function(
    function_id="admit_source_table_query",
    interface="llm.response_admission",
    description="Admit filters over available projected columns only.",
    input_type="structured JSON response and SourceTableDataset",
    output_type="SourceTableQuery",
    sources=((_BINDING_PATH, "propose_source_table_query"),),
    effect="Normalizes one deterministic query without choosing continuation.",
    failure_contract="Drops undeclared columns and empty literal filters.",
)

EXTRACT_SOURCE_TABLE_QUERY = source_function(
    function_id="extract_source_table_query",
    interface="evidence.extraction",
    description="Execute one admitted query over parsed source-table entities.",
    input_type="SourceTableQueryUnit",
    output_type="source-linked table records",
    sources=((_BINDING_PATH, "SourceTableBinding._extract_source_table_query"),),
    effect="Pure deterministic projection over admitted rows.",
    failure_contract="Never reads outside the detected source-table workspace.",
)

ACCEPT_SOURCE_TABLE_QUERY = source_function(
    function_id="accept_source_table_query",
    interface="evidence.acceptance",
    description="Commit exact table spans before proposing Goal results.",
    input_type="SourceTableQueryUnit and extracted records",
    output_type="evidence commit and record artifact IDs",
    sources=((_BINDING_PATH, "SourceTableBinding._accept_source_table_query"),),
    effect="Uses the durable evidence registry as the acceptance boundary.",
    failure_contract="A result without a complete accepted source chain mints no identity.",
)

BUILD_SOURCE_TABLE_RESULT = source_function(
    function_id="build_source_table_result",
    interface="handoff.child_result_builder",
    description="Build the source-table Episode's closed result for its parent Page.",
    input_type="completed source-table state and matching ParentRequest",
    output_type="handoff_library.ChildResult",
    sources=(
        (_BINDING_PATH, "SourceTableBinding._source_table_query_result"),
        (_PROVIDER_PATH, "ProviderRuntime._episode_result"),
    ),
    effect="Returns identities by channel, measurements, flags, and artifact IDs.",
    failure_contract="Never returns source table text, model rationales, or programs upward.",
)


BINDING = EpisodeBindingDeclaration(
    grain_name="source_table",
    interface="question_pipeline.source_table",
    topology_role=EpisodeTopologyRole.LEAF,
    goal="one detected source-table region and its Page-local information need",
    unit="one admitted query over parsed source-table entities",
    result="evidence-linked accepted table identities",
    progress=(
        "marginal dominated hypervolume over accepted stable identities kept "
        "distinct by declared result channel"
    ),
    stopping=(
        "continue while the upper uncertainty bound on predicted next marginal "
        "hypervolume exceeds the declared tolerance"
    ),
    admit_request=ADMIT_PARENT_REQUEST.bind(
        "admit_source_table_request",
        arguments={"payload_contract": REQUEST_PAYLOAD_CONTRACT.as_record()},
    ),
    open_source=SOURCE_TABLE_QUERY_SOURCE.bind("open_query_source"),
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
    build_result=BUILD_SOURCE_TABLE_RESULT.bind(
        "build_source_table_result",
        arguments={"payload_contract": RESULT_PAYLOAD_CONTRACT.as_record()},
    ),
    components=(
        SCOPE_QUESTION_TABLE_GOAL.bind("scope_goal"),
        PROJECT_GOAL_PROMPT.bind("project_goal_prompt"),
        STRUCTURED_JSON_COMPLETION.bind(
            "interpret_table_program",
            arguments={
                "tier": ModelTier.REASONING.value,
                "system_prompt": PROGRAM_SYSTEM_PROMPT,
                "prompt_template": PROGRAM_PROMPT,
            },
        ),
        ADMIT_TABLE_PROGRAM.bind("admit_table_program"),
        STRUCTURED_JSON_COMPLETION.bind(
            "resolve_mentions",
            arguments={
                "tier": ModelTier.REASONING.value,
                "system_prompt": COMMUNITY_SYSTEM_PROMPT,
                "prompt_template": COMMUNITY_PROMPT,
            },
        ),
        ADMIT_MENTION_COMMUNITIES.bind("admit_mention_communities"),
        STRUCTURED_JSON_COMPLETION.bind(
            "propose_query",
            arguments={
                "tier": ModelTier.REASONING.value,
                "system_prompt": QUERY_SYSTEM_PROMPT,
                "prompt_template": QUERY_PROMPT,
            },
        ),
        ADMIT_SOURCE_TABLE_QUERY.bind("admit_query"),
        EXTRACT_SOURCE_TABLE_QUERY.bind("extract_query"),
        ACCEPT_SOURCE_TABLE_QUERY.bind("accept_evidence"),
        PROJECT_DIRECT_EVIDENCE_CANDIDATES.bind("project_direct_candidates"),
        PROPOSE_TABLE_RESULTS.bind("propose_table_results"),
        PROJECT_ACCEPTED_IDENTITY_CHANNELS.bind("project_accepted_identities"),
    ),
)

DESIGN = EpisodeLibraryDesign(
    qualified_name="question_pipeline.source_table",
    title="Source-table interpreter and query loop",
    binding=BINDING,
    function_definitions=(
        ADMIT_PARENT_REQUEST,
        SOURCE_TABLE_QUERY_SOURCE,
        RESULT_COLUMN_SCHEMA,
        COMPOSE_INCIDENCE_CONTROLLER,
        MARGINAL_DOMINATED_HYPERVOLUME,
        PAIRED_INCIDENCE,
        PREDICTED_CREDIT_UPPER_BOUND,
        BUILD_SOURCE_TABLE_RESULT,
        SCOPE_QUESTION_TABLE_GOAL,
        PROJECT_GOAL_PROMPT,
        STRUCTURED_JSON_COMPLETION,
        ADMIT_TABLE_PROGRAM,
        ADMIT_MENTION_COMMUNITIES,
        ADMIT_SOURCE_TABLE_QUERY,
        EXTRACT_SOURCE_TABLE_QUERY,
        ACCEPT_SOURCE_TABLE_QUERY,
        PROJECT_DIRECT_EVIDENCE_CANDIDATES,
        PROPOSE_TABLE_RESULTS,
        PROJECT_ACCEPTED_IDENTITY_CHANNELS,
    ),
    source_symbols=(
        source_symbol(_BINDING_PATH, "SourceTableBinding"),
        source_symbol(_BINDING_PATH, "SourceTableQuerySource"),
        source_symbol(_BINDING_PATH, "interpret_source_table_region"),
        source_symbol(_BINDING_PATH, "propose_source_table_query"),
    ),
)


__all__ = [
    "BINDING",
    "COMMUNITY_PROMPT",
    "DESIGN",
    "PROGRAM_PROMPT",
    "QUERY_PROMPT",
    "REQUEST_PAYLOAD_CONTRACT",
    "RESULT_PAYLOAD_CONTRACT",
]
