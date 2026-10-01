"""Report Episode: read ordered prose windows with compact source-linked memory."""

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


_BINDING_PATH = "question_pipeline/episode_binding/report_binding.py"
_PROVIDER_PATH = "question_pipeline/episode_binding/provider_binding.py"

UNCERTAINTY_ALPHA = 0.05
STOP_WHEN_PREDICTED_CREDIT_UPPER_AT_MOST = 0.01

REQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract(
    artifact_roles=("goal_scope", "unit"),
    required_artifact_roles=("goal_scope", "unit"),
)
RESULT_PAYLOAD_CONTRACT = HandoffPayloadContract()

REPORT_SYSTEM_PROMPT = (
    "You read one ordered window of a longer report. Return one JSON object "
    "containing compact source-linked memory and exact source-grounded Goal records."
)

REPORT_WINDOW_PROMPT = """QUESTION:
{question}

DECLARED GOAL CONTRACT:
{goal_contract_json}

CURRENT GOAL STATE:
{goal_state_json}

PAGE TITLE AND OUTLINE:
{outline_json}

EXACT BEGINNING OF THE PAGE:
{source_preview}

PARENT'S OBJECTIVE FOR THIS REPORT READING:
{objective}

COMPACT MEMORY FROM EARLIER WINDOWS OF THIS SAME REPORT:
{previous_memory_json}

CURRENT REPORT WINDOW, IN DOCUMENT ORDER:
{chunks_json}

Read the current window as part of one report, not as unrelated snippets.
Use the declared identity anchors to decide when facts in different sections
refer to the same subject and when they refer to different subjects. Preserve
one-to-many findings as separate Goal rows when the contract declares them as
separate findings.

Return an updated compact memory that retains only information useful for
resolving later sections: subject identities and aliases, dates and locations,
relationships among mentions, unresolved links, and exact short evidence
quotes with their source_chunk_ids. Preserve relevant earlier memory. The
memory is working context only: it is not accepted evidence and earns no
credit.

Also return every Goal record that is now sufficiently resolved. Reported
values must be exact source wording or harmless numeric formatting of it.
Never infer or estimate a reported value. Each record must name one declared
Goal table, contain only that table's declared columns, and cite exact supplied
source_chunk_ids.

Return exactly:
{{
  "memory": {{"a compact task-appropriate working memory": "..."}},
  "records": [
    {{
      "table": "one declared Goal table",
      "values": {{"declared_column": "exact reported value"}},
      "source_chunk_ids": ["one or more supplied source chunk ids"]
    }}
  ]
}}"""


REPORT_WINDOW_SOURCE = source_function(
    function_id="report_window_source",
    interface="episode.unit_source",
    description="Pull the next ordered, previously unread report window.",
    input_type="report state and Episode view",
    output_type="ReportWindowUnit or source exhaustion",
    sources=((_BINDING_PATH, "ReportWindowSource"),),
    effect="Advances document order while retaining compact report memory.",
    failure_contract="Does not skip or reorder a window based on expected yield.",
)

ADMIT_REPORT_WINDOW = source_function(
    function_id="admit_report_window_extraction",
    interface="llm.response_admission",
    description="Admit declared columns and supplied source chunk IDs only.",
    input_type="structured JSON model response and current window catalog",
    output_type="ReportWindowExtraction",
    sources=((_BINDING_PATH, "extract_report_window"),),
    effect="Projects model output into exact source-linked records and memory.",
    failure_contract="Rejects malformed memory and drops undeclared records or citations.",
)

ACCEPT_REPORT_WINDOW = source_function(
    function_id="accept_report_window",
    interface="evidence.acceptance",
    description="Commit exact report spans before proposing table results.",
    input_type="ReportWindowUnit and extracted report records",
    output_type="evidence commit and record artifact IDs",
    sources=((_BINDING_PATH, "ReportBinding._accept_report_window"),),
    effect="Writes durable evidence through the evidence acceptance boundary.",
    failure_contract="A record without a complete source chain mints no identity.",
)

BUILD_REPORT_RESULT = source_function(
    function_id="build_report_result",
    interface="handoff.child_result_builder",
    description="Build the report's closed result for its parent Page.",
    input_type="completed report state and matching ParentRequest",
    output_type="handoff_library.ChildResult",
    sources=(
        (_BINDING_PATH, "ReportBinding._report_window_result"),
        (_PROVIDER_PATH, "ProviderRuntime._episode_result"),
    ),
    effect="Returns identities by channel, measurements, flags, and artifact IDs.",
    failure_contract="Never returns report prose, model memory, or prompt text upward.",
)


BINDING = EpisodeBindingDeclaration(
    grain_name="report",
    interface="question_pipeline.report",
    topology_role=EpisodeTopologyRole.LEAF,
    goal="one report proposal within its Page Goal",
    unit="one ordered report window",
    result="source-linked accepted table identities",
    progress=(
        "marginal dominated hypervolume over accepted stable identities kept "
        "distinct by declared result channel"
    ),
    stopping=(
        "continue while the upper uncertainty bound on predicted next marginal "
        "hypervolume exceeds the declared tolerance"
    ),
    admit_request=ADMIT_PARENT_REQUEST.bind(
        "admit_report_request",
        arguments={"payload_contract": REQUEST_PAYLOAD_CONTRACT.as_record()},
    ),
    open_source=REPORT_WINDOW_SOURCE.bind("open_report_source"),
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
    build_result=BUILD_REPORT_RESULT.bind(
        "build_report_result",
        arguments={"payload_contract": RESULT_PAYLOAD_CONTRACT.as_record()},
    ),
    components=(
        SCOPE_QUESTION_TABLE_GOAL.bind("scope_goal"),
        PROJECT_GOAL_PROMPT.bind("project_goal_prompt"),
        STRUCTURED_JSON_COMPLETION.bind(
            "extract_report_window",
            arguments={
                "tier": ModelTier.REASONING.value,
                "system_prompt": REPORT_SYSTEM_PROMPT,
                "prompt_template": REPORT_WINDOW_PROMPT,
            },
        ),
        ADMIT_REPORT_WINDOW.bind("admit_report_window"),
        ACCEPT_REPORT_WINDOW.bind("accept_evidence"),
        PROJECT_DIRECT_EVIDENCE_CANDIDATES.bind("project_direct_candidates"),
        PROPOSE_TABLE_RESULTS.bind("propose_table_results"),
        PROJECT_ACCEPTED_IDENTITY_CHANNELS.bind("project_accepted_identities"),
    ),
)

DESIGN = EpisodeLibraryDesign(
    qualified_name="question_pipeline.report",
    title="Ordered report reader",
    binding=BINDING,
    function_definitions=(
        ADMIT_PARENT_REQUEST,
        REPORT_WINDOW_SOURCE,
        RESULT_COLUMN_SCHEMA,
        COMPOSE_INCIDENCE_CONTROLLER,
        MARGINAL_DOMINATED_HYPERVOLUME,
        PAIRED_INCIDENCE,
        PREDICTED_CREDIT_UPPER_BOUND,
        BUILD_REPORT_RESULT,
        SCOPE_QUESTION_TABLE_GOAL,
        PROJECT_GOAL_PROMPT,
        STRUCTURED_JSON_COMPLETION,
        ADMIT_REPORT_WINDOW,
        ACCEPT_REPORT_WINDOW,
        PROJECT_DIRECT_EVIDENCE_CANDIDATES,
        PROPOSE_TABLE_RESULTS,
        PROJECT_ACCEPTED_IDENTITY_CHANNELS,
    ),
    source_symbols=(
        source_symbol(_BINDING_PATH, "ReportBinding"),
        source_symbol(_BINDING_PATH, "ReportWindowSource"),
        source_symbol(_BINDING_PATH, "extract_report_window"),
    ),
)


__all__ = [
    "BINDING",
    "DESIGN",
    "REPORT_SYSTEM_PROMPT",
    "REPORT_WINDOW_PROMPT",
    "REQUEST_PAYLOAD_CONTRACT",
    "RESULT_PAYLOAD_CONTRACT",
]
