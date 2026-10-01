"""Web-search Episode: acquire a result list and choose measured Page children."""

from handoff_library import ADMIT_PARENT_REQUEST, HandoffPayloadContract
from llm_call_library import ModelTier, PROBABILITY_JUDGMENT, STRUCTURED_JSON_COMPLETION
from method_loop import (
    EpisodeBindingDeclaration,
    EpisodeChildSlot,
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
    PROJECT_GOAL_PROMPT,
    RESULT_COLUMN_SCHEMA,
    SCOPE_QUESTION_TABLE_GOAL,
)

from .models import EpisodeLibraryDesign
from .page import (
    REQUEST_PAYLOAD_CONTRACT as PAGE_REQUEST_PAYLOAD_CONTRACT,
    RESULT_PAYLOAD_CONTRACT as PAGE_RESULT_PAYLOAD_CONTRACT,
)
from .provenance import source_function, source_symbol


_BINDING_PATH = "question_pipeline/episode_binding/web_search_binding.py"
_PAGE_BINDING_PATH = "question_pipeline/episode_binding/page_binding.py"
_PROVIDER_PATH = "question_pipeline/episode_binding/provider_binding.py"

UNCERTAINTY_ALPHA = 0.05
STOP_WHEN_PREDICTED_CREDIT_UPPER_AT_MOST = 0.01

REQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract(
    artifact_roles=("goal_scope", "unit"),
    required_artifact_roles=("goal_scope", "unit"),
)
RESULT_PAYLOAD_CONTRACT = HandoffPayloadContract()

CANDIDATE_RELEVANCE_SYSTEM_PROMPT = (
    "Judge one supplied page-text window against one declared Search Goal and "
    "return only the admitted probability. Make no acquisition decision."
)

CANDIDATE_RELEVANCE_PROMPT = """SEARCH GOAL:
{search_goal_json}

SEARCH QUERY:
{search_query}

CANDIDATE METADATA:
{candidate_json}

CANDIDATE TEXT WINDOW:
{candidate_text_window}

Could this window contain evidence that fills at least one requested result for
an identifiable subject of the Search Goal? Judge possible contribution to the
declared result, not broad topical similarity.

True means the text contains a reported value, an evidence-based basis for a
permitted estimate, or identity/context needed to connect such a value to a
requested subject. False means the text cannot contribute any requested result
even if it mentions the broad topic."""

PAGE_SELECTION_SYSTEM_PROMPT = (
    "You choose one Page child from a supplied Search candidate catalog. "
    "Return one JSON object. Never decide whether acquisition continues."
)

PAGE_SELECTION_PROMPT = """SEARCH EPISODE GOAL:
{goal_json}

UNPROCESSED PAGE CANDIDATES:
{candidates_json}

PREVIOUS PAGE CHILDREN AND THEIR MEASURED RESULTS:
{previous_pages_json}

Choose exactly one option_id from UNPROCESSED PAGE CANDIDATES.

Each candidate contains its original provider rank and a probability that the
page can contribute to the Search Goal. These are measurements for planning,
not a rule that the largest probability must be selected. Use the title,
description, provider rank, assessment, and realized results of previous Page
children to choose the next Page worth processing.

The Search Episode's numerical controller has already decided that another
Page may be attempted. Choose which Page to try; never decide whether the
Search continues or stops.

Return exactly:
{{
  "option_id": "one exact option_id from UNPROCESSED PAGE CANDIDATES",
  "objective": "the Goal information this Page should seek",
  "rationale": "how candidate evidence and prior measured Page results support this choice"
}}"""


ACQUIRE_SEARCH_RESULTS = source_function(
    function_id="acquire_search_results",
    interface="search.result_acquisition",
    description="Issue the strategy's declared search task to its bound provider.",
    input_type="SearchTask and provider binding",
    output_type="ordered provider result list",
    sources=((_BINDING_PATH, "SearchPageProposer._issue"),),
    effect="Acquires one result list and records provider outcome artifacts.",
    failure_contract="Provider failure becomes typed source failure, not zero yield.",
)

AGGREGATE_CANDIDATE_ASSESSMENT = source_function(
    function_id="aggregate_candidate_assessment",
    interface="assessment.window_aggregation",
    description="Window candidate text and retain the maximum admitted probability.",
    input_type="page candidate, Goal, and per-window probability callable",
    output_type="PageCandidateAssessment",
    sources=((_BINDING_PATH, "assess_page_candidate"),),
    effect="Produces planning measurements without selecting or rejecting a Page.",
    failure_contract="Assessment failure remains distinct from irrelevant content.",
)

ADMIT_PAGE_SELECTION = source_function(
    function_id="admit_search_page_selection",
    interface="llm.response_admission",
    description="Admit exactly one currently available option ID.",
    input_type="structured JSON response and current candidate catalog",
    output_type="SearchPageProposal",
    sources=((_BINDING_PATH, "propose_search_page"),),
    effect="Validates selection and provider rank without deciding continuation.",
    failure_contract="Rejects undeclared, consumed, or rankless options.",
)

SEARCH_PAGE_SOURCE = source_function(
    function_id="search_page_source",
    interface="episode.unit_source",
    description="Assess unprocessed results and pull the selected Page child.",
    input_type="search state and Episode view",
    output_type="Page child proposal or source exhaustion",
    sources=((_BINDING_PATH, "SearchPageProposer"),),
    effect="Maintains result-list position, assessments, and measured Page history.",
    failure_contract="Never converts acquisition or assessment failure into no evidence.",
)

BUILD_PAGE = source_function(
    function_id="build_page",
    interface="episode.child_builder",
    description="Build the selected Page Episode from its closed request.",
    input_type="typed Page ParentRequest",
    output_type="question_pipeline.page Episode",
    sources=((_PAGE_BINDING_PATH, "PageBinding._make_page_item"),),
    effect="Constructs a Page with its own Goal, controller, and loop.",
    failure_contract="Rejects a mismatched candidate, request, or Goal lineage.",
)

PREPARE_PAGE_REQUEST = source_function(
    function_id="prepare_page_request",
    interface="handoff.parent_request_projection",
    description="Project selected candidate and scoped Goal artifact IDs for Page.",
    input_type="search state, selected candidate, and child identity",
    output_type="handoff_library.ParentRequest",
    sources=((_BINDING_PATH, "SearchPageProposer.next"),),
    effect="Creates the closed request owned by the search-to-Page edge.",
    failure_contract="Rejects unknown artifact, measurement, state, and flag roles.",
)

RECEIVE_PAGE_RESULT = source_function(
    function_id="receive_page_result",
    interface="handoff.child_result_projection",
    description="Admit Page output and project identities for Search-local credit.",
    input_type="search state, matching request, ChildResult, and EpisodeCompletion",
    output_type="CreditObservation on the Search scale",
    sources=(
        (_BINDING_PATH, "WebSearchBinding._page_episode_result"),
        (_BINDING_PATH, "WebSearchBinding._on_page"),
    ),
    effect="Checks correlation and recomputes the parent-local identity vector.",
    failure_contract="Rejects cross-wired Page results and undeclared payload roles.",
)

BUILD_WEB_SEARCH_RESULT = source_function(
    function_id="build_web_search_result",
    interface="handoff.child_result_builder",
    description="Build the Search Episode's closed result for its strategy parent.",
    input_type="completed search state and matching ParentRequest",
    output_type="handoff_library.ChildResult",
    sources=(
        (_BINDING_PATH, "WebSearchBinding._close_search"),
        (_PROVIDER_PATH, "ProviderRuntime._episode_result"),
    ),
    effect="Returns identities by channel, measurements, flags, and artifact IDs.",
    failure_contract="Never returns provider prose, page text, or model rationales upward.",
)


BINDING = EpisodeBindingDeclaration(
    grain_name="search",
    interface="question_pipeline.web_search",
    topology_role=EpisodeTopologyRole.BRANCH,
    goal="one search task within its parent strategy Goal",
    unit="one selected and processed Page Episode",
    result="a Search-local accepted-identity result",
    progress=(
        "marginal dominated hypervolume over accepted stable identities kept "
        "distinct by declared result channel"
    ),
    stopping=(
        "continue while the upper uncertainty bound on predicted next marginal "
        "hypervolume exceeds the declared tolerance"
    ),
    admit_request=ADMIT_PARENT_REQUEST.bind(
        "admit_web_search_request",
        arguments={"payload_contract": REQUEST_PAYLOAD_CONTRACT.as_record()},
    ),
    open_source=SEARCH_PAGE_SOURCE.bind("open_page_source"),
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
    build_result=BUILD_WEB_SEARCH_RESULT.bind(
        "build_web_search_result",
        arguments={"payload_contract": RESULT_PAYLOAD_CONTRACT.as_record()},
    ),
    components=(
        SCOPE_QUESTION_TABLE_GOAL.bind("scope_goal"),
        PROJECT_GOAL_PROMPT.bind("project_goal_prompt"),
        ACQUIRE_SEARCH_RESULTS.bind("acquire_results"),
        PROBABILITY_JUDGMENT.bind(
            "judge_candidate_window",
            arguments={
                "tier": ModelTier.FAST.value,
                "system_prompt": CANDIDATE_RELEVANCE_SYSTEM_PROMPT,
                "prompt_template": CANDIDATE_RELEVANCE_PROMPT,
            },
        ),
        AGGREGATE_CANDIDATE_ASSESSMENT.bind("assess_candidate"),
        STRUCTURED_JSON_COMPLETION.bind(
            "propose_page",
            arguments={
                "tier": ModelTier.FAST.value,
                "system_prompt": PAGE_SELECTION_SYSTEM_PROMPT,
                "prompt_template": PAGE_SELECTION_PROMPT,
            },
        ),
        ADMIT_PAGE_SELECTION.bind("admit_page_selection"),
    ),
    child_slots=(
        EpisodeChildSlot(
            name="page",
            accepted_interfaces=("question_pipeline.page",),
            build_child=BUILD_PAGE.bind("build_page"),
            prepare_request=PREPARE_PAGE_REQUEST.bind(
                "prepare_page_request",
                arguments={
                    "payload_contract": PAGE_REQUEST_PAYLOAD_CONTRACT.as_record()
                },
            ),
            receive_result=RECEIVE_PAGE_RESULT.bind(
                "receive_page_result",
                arguments={
                    "payload_contract": PAGE_RESULT_PAYLOAD_CONTRACT.as_record()
                },
            ),
        ),
    ),
)

DESIGN = EpisodeLibraryDesign(
    qualified_name="question_pipeline.web_search",
    title="Web search and Page selection",
    binding=BINDING,
    function_definitions=(
        ADMIT_PARENT_REQUEST,
        SEARCH_PAGE_SOURCE,
        RESULT_COLUMN_SCHEMA,
        COMPOSE_INCIDENCE_CONTROLLER,
        MARGINAL_DOMINATED_HYPERVOLUME,
        PAIRED_INCIDENCE,
        PREDICTED_CREDIT_UPPER_BOUND,
        BUILD_WEB_SEARCH_RESULT,
        SCOPE_QUESTION_TABLE_GOAL,
        PROJECT_GOAL_PROMPT,
        ACQUIRE_SEARCH_RESULTS,
        PROBABILITY_JUDGMENT,
        AGGREGATE_CANDIDATE_ASSESSMENT,
        STRUCTURED_JSON_COMPLETION,
        ADMIT_PAGE_SELECTION,
        BUILD_PAGE,
        PREPARE_PAGE_REQUEST,
        RECEIVE_PAGE_RESULT,
    ),
    source_symbols=(
        source_symbol(_BINDING_PATH, "WebSearchBinding"),
        source_symbol(_BINDING_PATH, "SearchPageProposer"),
        source_symbol(_BINDING_PATH, "propose_search_page"),
        source_symbol(_BINDING_PATH, "assess_page_candidate"),
    ),
)


__all__ = [
    "BINDING",
    "CANDIDATE_RELEVANCE_PROMPT",
    "DESIGN",
    "PAGE_SELECTION_PROMPT",
    "REQUEST_PAYLOAD_CONTRACT",
    "RESULT_PAYLOAD_CONTRACT",
]
