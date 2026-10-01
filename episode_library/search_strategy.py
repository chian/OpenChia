"""Search-strategy Episode: repeatedly open measured web-search Episodes."""

from handoff_library import ADMIT_PARENT_REQUEST, HandoffPayloadContract
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
from .provenance import source_function, source_symbol
from .web_search import (
    REQUEST_PAYLOAD_CONTRACT as WEB_SEARCH_REQUEST_PAYLOAD_CONTRACT,
    RESULT_PAYLOAD_CONTRACT as WEB_SEARCH_RESULT_PAYLOAD_CONTRACT,
)


_BINDING_PATH = "question_pipeline/episode_binding/strategy_binding.py"
_PROVIDER_PATH = "question_pipeline/episode_binding/provider_binding.py"
_WEB_SEARCH_PATH = "question_pipeline/episode_binding/web_search_binding.py"

UNCERTAINTY_ALPHA = 0.05
STOP_WHEN_PREDICTED_CREDIT_UPPER_AT_MOST = 0.01

REQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract(
    artifact_roles=("goal_scope", "unit"),
    required_artifact_roles=("goal_scope", "unit"),
)
RESULT_PAYLOAD_CONTRACT = HandoffPayloadContract()


STRATEGY_SEARCH_SOURCE = source_function(
    function_id="strategy_search_source",
    interface="episode.unit_source",
    description="Pull one still-eligible search task for this strategy.",
    input_type="strategy Goal view and measured prior search results",
    output_type="web-search child proposal or source exhaustion",
    sources=((_BINDING_PATH, "StrategySearches"),),
    effect="Selects a search unit; it makes no continuation decision.",
    failure_contract="Returns typed source failure without fabricating a search result.",
)

BUILD_WEB_SEARCH = source_function(
    function_id="build_web_search",
    interface="episode.child_builder",
    description="Build the selected web-search Episode from its prepared request.",
    input_type="typed web-search ParentRequest",
    output_type="question_pipeline.web_search Episode",
    sources=((_WEB_SEARCH_PATH, "WebSearchBinding._build_search_episode"),),
    effect="Constructs a child with its own Goal, controller, and loop.",
    failure_contract="Rejects an undeclared search child or mismatched Goal lineage.",
)

PREPARE_WEB_SEARCH_REQUEST = source_function(
    function_id="prepare_web_search_request",
    interface="handoff.parent_request_projection",
    description="Project only the selected task and scoped Goal artifact IDs.",
    input_type="strategy state, selected search task, and child identity",
    output_type="handoff_library.ParentRequest",
    sources=((_BINDING_PATH, "StrategySearches.next"),),
    effect="Creates the closed request owned by the strategy-to-search edge.",
    failure_contract="Rejects unknown task, artifact, measurement, state, and flag roles.",
)

RECEIVE_WEB_SEARCH_RESULT = source_function(
    function_id="receive_web_search_result",
    interface="handoff.child_result_projection",
    description="Admit a search result and project its identities for strategy credit.",
    input_type="strategy state, matching request, ChildResult, and EpisodeCompletion",
    output_type="CreditObservation on the strategy's scale",
    sources=(
        (_BINDING_PATH, "StrategyBinding._search_episode_result"),
        (_BINDING_PATH, "StrategyBinding._close_strategy"),
    ),
    effect="Checks correlation and recomputes the parent-local identity vector.",
    failure_contract="Rejects cross-wired results and incomplete undeclared payloads.",
)

BUILD_STRATEGY_RESULT = source_function(
    function_id="build_strategy_result",
    interface="handoff.child_result_builder",
    description="Build the strategy's closed result for its parent run.",
    input_type="completed strategy state and its admitted request",
    output_type="handoff_library.ChildResult",
    sources=(
        (_BINDING_PATH, "StrategyBinding._search_episode_result"),
        (_PROVIDER_PATH, "ProviderRuntime._episode_result"),
    ),
    effect="Returns logical identities, numeric measurements, flags, and artifact IDs.",
    failure_contract="Never returns raw search text, prompts, rationales, or source bodies.",
)


BINDING = EpisodeBindingDeclaration(
    grain_name="strategy",
    interface="question_pipeline.search_strategy",
    topology_role=EpisodeTopologyRole.BRANCH,
    goal="one strategy family, its strategy key, and its seed queries",
    unit="one completed web-search Episode",
    result="a strategy-local accepted-identity result",
    progress=(
        "marginal dominated hypervolume over accepted stable identities kept "
        "distinct by declared result channel"
    ),
    stopping=(
        "continue while the upper uncertainty bound on predicted next marginal "
        "hypervolume exceeds the declared tolerance"
    ),
    admit_request=ADMIT_PARENT_REQUEST.bind(
        "admit_strategy_request",
        arguments={"payload_contract": REQUEST_PAYLOAD_CONTRACT.as_record()},
    ),
    open_source=STRATEGY_SEARCH_SOURCE.bind("open_search_source"),
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
    build_result=BUILD_STRATEGY_RESULT.bind(
        "build_strategy_result",
        arguments={"payload_contract": RESULT_PAYLOAD_CONTRACT.as_record()},
    ),
    components=(
        SCOPE_QUESTION_TABLE_GOAL.bind("scope_goal"),
        PROJECT_GOAL_PROMPT.bind("project_goal_prompt"),
    ),
    child_slots=(
        EpisodeChildSlot(
            name="web_search",
            accepted_interfaces=("question_pipeline.web_search",),
            build_child=BUILD_WEB_SEARCH.bind("build_web_search"),
            prepare_request=PREPARE_WEB_SEARCH_REQUEST.bind(
                "prepare_web_search_request",
                arguments={
                    "payload_contract": (
                        WEB_SEARCH_REQUEST_PAYLOAD_CONTRACT.as_record()
                    )
                },
            ),
            receive_result=RECEIVE_WEB_SEARCH_RESULT.bind(
                "receive_web_search_result",
                arguments={
                    "payload_contract": (
                        WEB_SEARCH_RESULT_PAYLOAD_CONTRACT.as_record()
                    )
                },
            ),
        ),
    ),
)

DESIGN = EpisodeLibraryDesign(
    qualified_name="question_pipeline.search_strategy",
    title="Search strategy",
    binding=BINDING,
    function_definitions=(
        ADMIT_PARENT_REQUEST,
        STRATEGY_SEARCH_SOURCE,
        RESULT_COLUMN_SCHEMA,
        COMPOSE_INCIDENCE_CONTROLLER,
        MARGINAL_DOMINATED_HYPERVOLUME,
        PAIRED_INCIDENCE,
        PREDICTED_CREDIT_UPPER_BOUND,
        BUILD_STRATEGY_RESULT,
        SCOPE_QUESTION_TABLE_GOAL,
        PROJECT_GOAL_PROMPT,
        BUILD_WEB_SEARCH,
        PREPARE_WEB_SEARCH_REQUEST,
        RECEIVE_WEB_SEARCH_RESULT,
    ),
    source_symbols=(
        source_symbol(_BINDING_PATH, "StrategyBinding"),
        source_symbol(_BINDING_PATH, "StrategySearches"),
    ),
)


__all__ = [
    "BINDING",
    "DESIGN",
    "REQUEST_PAYLOAD_CONTRACT",
    "RESULT_PAYLOAD_CONTRACT",
]
