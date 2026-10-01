"""Root question-run Episode: sample and measure search-strategy Episodes."""

from handoff_library import ADMIT_DUET_LAUNCH_REQUEST, HandoffPayloadContract
from llm_call_library import ModelTier, STRUCTURED_JSON_COMPLETION
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
    CHECKPOINT_QUESTION_TABLE_GOAL,
    OPEN_QUESTION_TABLE_GOAL,
    PROJECT_GOAL_PROMPT,
    RESULT_COLUMN_SCHEMA,
    RESTORE_QUESTION_TABLE_GOAL,
    SCOPE_QUESTION_TABLE_GOAL,
)

from .models import EpisodeLibraryDesign
from .provenance import source_function, source_symbol
from .search_strategy import (
    REQUEST_PAYLOAD_CONTRACT as STRATEGY_REQUEST_PAYLOAD_CONTRACT,
    RESULT_PAYLOAD_CONTRACT as STRATEGY_RESULT_PAYLOAD_CONTRACT,
)


_BINDING_PATH = "question_pipeline/episode_binding/run_binding.py"
_PROVIDER_PATH = "question_pipeline/episode_binding/provider_binding.py"
_SEARCH_PATH = "question_pipeline/utilities/search.py"

UNCERTAINTY_ALPHA = 0.05
STOP_WHEN_PREDICTED_CREDIT_UPPER_AT_MOST = 0.01

LAUNCH_PAYLOAD_CONTRACT = HandoffPayloadContract(
    artifact_roles=("workflow_spec",),
    required_artifact_roles=("workflow_spec",),
)

STRATEGY_SYSTEM_PROMPT = (
    "Propose source-search strategy strings from the supplied Goal, measured "
    "history, deficits, and operator catalog. Return one JSON object. Do not "
    "decide whether the run continues."
)

STRATEGY_PROMPT = """QUESTION:
{question}

RUN VIEW, INCLUDING DECLARED CONTRACT AND OBSERVED DEFICITS:
{run_view_json}

STRATEGIES ALREADY OPENED AND THEIR MEASURED RESULTS:
{tried_strategies_json}

AVAILABLE OPERATOR CATALOG:
{operator_catalog_json}

Propose further search strategies for this run. A strategy is one operator
from the supplied catalog, applied to one or more declared target IDs, with
seed phrasings showing how searches would be worded.

Use completed strategy outcomes as empirical memory. Compare what prior
queries attempted with distinct findings overall and by result channel,
incidence estimates, acquired sources, duplicate URLs, page outcomes,
failures, and unprocessed results. Identify vocabulary and source shapes that
yielded new evidence, saturated, repeated known material, or were never judged
because acquisition or extraction failed.

Treat the requested result as a whole. Additional subjects are low value when
their rows repeat already populated fields while other requested fields remain
sparse. Use observed deficits, findings by channel, and realized method credit
to choose what information the next search should seek.

For known rows with missing fields, combine their declared identity anchors
with terms for those missing fields. When the same field is absent across many
rows, seek a source shape likely to report it across subjects; when only a few
rows remain, target those subjects. Name sparse requested categories rather
than repeating well-populated broad topics.

Build on productive vocabulary or source shapes while their fitted remaining
yield supports doing so. Change terminology, source shape, target, or operator
when prior work saturated or mostly repeated evidence. Instrument failure is
not evidence that a subject direction is barren.

Every operator must be an exact catalog key and every target ID must be
declared in the run view. When observed deficits exist, proposals must name the
deficit IDs they address and their query seeds must visibly address the missing
fields and anchors. Order proposals by expected marginal contribution of
distinct evidence to those deficits.

For each proposal, report semantic distance from the nearest strategy already
opened on a 0.0-1.0 scale, where 0.0 is the same operator/targets/phrasing and
1.0 shares nothing with prior strategies. The model reports semantic distance;
the numerical selector applies the declared distance rule.

Return exactly:
{{
  "proposals": [
    {{
      "operator": "one exact catalog key",
      "target_ids": ["declared target ids"],
      "query_seeds": ["seed phrasing", "seed phrasing"],
      "distance": 0.0,
      "label": "short generic name",
      "rationale": "measured support, material change, and target deficit"
    }}
  ]
}}"""


ADMIT_STRATEGY_PROPOSALS = source_function(
    function_id="admit_strategy_proposals",
    interface="llm.response_admission",
    description="Admit catalog operators, declared targets, seeds, and semantic distance.",
    input_type="structured JSON response, operator catalog, and declared target IDs",
    output_type="strategy proposal records",
    sources=((_SEARCH_PATH, "propose_distant_strategy"),),
    effect="Normalizes model-authored strings and distance without deciding continuation.",
    failure_contract="Rejects unknown operators and targets; never renames them to a neighbor.",
)

STRATEGY_SOURCE = source_function(
    function_id="strategy_source",
    interface="episode.unit_source",
    description="Select a semantically distinct strategy proposal for the run.",
    input_type="run Goal view, measured strategy history, and admitted proposals",
    output_type="search-strategy child proposal or source exhaustion",
    sources=((_BINDING_PATH, "StrategyProposer"),),
    effect="Selects strategy strings; it makes no run continuation decision.",
    failure_contract="A failed proposal call is not recorded as an unproductive strategy.",
)

BUILD_SEARCH_STRATEGY = source_function(
    function_id="build_search_strategy",
    interface="episode.child_builder",
    description="Build the selected search-strategy Episode from its closed request.",
    input_type="typed strategy ParentRequest",
    output_type="question_pipeline.search_strategy Episode",
    sources=((_BINDING_PATH, "StrategyProposer._open"),),
    effect="Constructs a child with its own Goal, controller, and loop.",
    failure_contract="Rejects mismatched proposal identity and Goal lineage.",
)

PREPARE_STRATEGY_REQUEST = source_function(
    function_id="prepare_strategy_request",
    interface="handoff.parent_request_projection",
    description="Project selected strategy and scoped Goal artifact IDs.",
    input_type="run state, selected strategy, and child identity",
    output_type="handoff_library.ParentRequest",
    sources=((_BINDING_PATH, "StrategyProposer._open"),),
    effect="Creates the closed request owned by the run-to-strategy edge.",
    failure_contract="Rejects unknown artifact, measurement, state, and flag roles.",
)

RECEIVE_STRATEGY_RESULT = source_function(
    function_id="receive_strategy_result",
    interface="handoff.child_result_projection",
    description="Admit a strategy result and project identities for run-local credit.",
    input_type="run state, matching request, ChildResult, and EpisodeCompletion",
    output_type="CreditObservation on the run scale",
    sources=(
        (_BINDING_PATH, "RunBinding._strategy_episode_result"),
        (_BINDING_PATH, "RunBinding._on_strategy"),
    ),
    effect="Checks correlation and recomputes the run's identity vector.",
    failure_contract="Rejects cross-wired results and never sums child hypervolume.",
)

BUILD_RUN_RESULT = source_function(
    function_id="build_run_result",
    interface="handoff.workflow_result_builder",
    description="Build the root result and immutable artifact references for Duet.",
    input_type="completed run record and global question-table Goal",
    output_type="closed workflow result",
    sources=(
        (_BINDING_PATH, "RunBinding"),
        (_PROVIDER_PATH, "RecordBinding.run_summary"),
    ),
    effect="Returns Goal-related results and log/checkpoint artifact locations.",
    failure_contract="Never embeds raw child prompts, source bodies, or executable capabilities.",
)


BINDING = EpisodeBindingDeclaration(
    grain_name="run",
    interface="question_pipeline.run",
    topology_role=EpisodeTopologyRole.BRANCH,
    goal="the root question Goal and its declared result contract",
    unit="one completed search-strategy Episode",
    result="the root accepted Goal state and durable run artifact references",
    progress=(
        "marginal dominated hypervolume over accepted stable identities kept "
        "distinct by declared result channel"
    ),
    stopping=(
        "continue while the upper uncertainty bound on predicted next marginal "
        "hypervolume exceeds the declared tolerance"
    ),
    admit_request=ADMIT_DUET_LAUNCH_REQUEST.bind(
        "admit_duet_launch",
        arguments={"payload_contract": LAUNCH_PAYLOAD_CONTRACT.as_record()},
    ),
    open_source=STRATEGY_SOURCE.bind("open_strategy_source"),
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
    build_result=BUILD_RUN_RESULT.bind("build_run_result"),
    components=(
        OPEN_QUESTION_TABLE_GOAL.bind("open_goal"),
        RESTORE_QUESTION_TABLE_GOAL.bind("restore_goal"),
        SCOPE_QUESTION_TABLE_GOAL.bind("scope_goal"),
        PROJECT_GOAL_PROMPT.bind("project_goal_prompt"),
        CHECKPOINT_QUESTION_TABLE_GOAL.bind("checkpoint_goal"),
        STRUCTURED_JSON_COMPLETION.bind(
            "propose_strategy",
            arguments={
                "tier": ModelTier.REASONING.value,
                "system_prompt": STRATEGY_SYSTEM_PROMPT,
                "prompt_template": STRATEGY_PROMPT,
            },
        ),
        ADMIT_STRATEGY_PROPOSALS.bind("admit_strategy_proposals"),
    ),
    child_slots=(
        EpisodeChildSlot(
            name="strategy",
            accepted_interfaces=("question_pipeline.search_strategy",),
            build_child=BUILD_SEARCH_STRATEGY.bind("build_search_strategy"),
            prepare_request=PREPARE_STRATEGY_REQUEST.bind(
                "prepare_strategy_request",
                arguments={
                    "payload_contract": (
                        STRATEGY_REQUEST_PAYLOAD_CONTRACT.as_record()
                    )
                },
            ),
            receive_result=RECEIVE_STRATEGY_RESULT.bind(
                "receive_strategy_result",
                arguments={
                    "payload_contract": (
                        STRATEGY_RESULT_PAYLOAD_CONTRACT.as_record()
                    )
                },
            ),
        ),
    ),
)

DESIGN = EpisodeLibraryDesign(
    qualified_name="question_pipeline.run",
    title="Question acquisition run",
    binding=BINDING,
    function_definitions=(
        ADMIT_DUET_LAUNCH_REQUEST,
        STRATEGY_SOURCE,
        RESULT_COLUMN_SCHEMA,
        COMPOSE_INCIDENCE_CONTROLLER,
        MARGINAL_DOMINATED_HYPERVOLUME,
        PAIRED_INCIDENCE,
        PREDICTED_CREDIT_UPPER_BOUND,
        BUILD_RUN_RESULT,
        OPEN_QUESTION_TABLE_GOAL,
        RESTORE_QUESTION_TABLE_GOAL,
        SCOPE_QUESTION_TABLE_GOAL,
        PROJECT_GOAL_PROMPT,
        CHECKPOINT_QUESTION_TABLE_GOAL,
        STRUCTURED_JSON_COMPLETION,
        ADMIT_STRATEGY_PROPOSALS,
        BUILD_SEARCH_STRATEGY,
        PREPARE_STRATEGY_REQUEST,
        RECEIVE_STRATEGY_RESULT,
    ),
    source_symbols=(
        source_symbol(_BINDING_PATH, "RunBinding"),
        source_symbol(_BINDING_PATH, "StrategyProposer"),
        source_symbol(_SEARCH_PATH, "propose_distant_strategy"),
    ),
)


__all__ = [
    "BINDING",
    "DESIGN",
    "LAUNCH_PAYLOAD_CONTRACT",
    "STRATEGY_PROMPT",
    "STRATEGY_SYSTEM_PROMPT",
]
