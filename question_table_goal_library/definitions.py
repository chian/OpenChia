"""Source-pinned function definitions for the question-table Goal boundary."""

from __future__ import annotations

from function_library import (
    FunctionImplementation,
    LibraryFunction,
    SourceSymbolReference,
)


_REPOSITORY = "https://github.com/chian/nano-graphrag"
_REVISION = "546526a77bd34ca79ea16f16549640d22fa86851"
_TABLES = "question_pipeline/utilities/tables.py"
_BINDING = "question_pipeline/episode_binding/provider_binding.py"


def _symbol(path: str, symbol: str) -> SourceSymbolReference:
    return SourceSymbolReference(
        repository=_REPOSITORY,
        revision=_REVISION,
        path=path,
        symbol=symbol,
    )


def _definition(
    *,
    function_id: str,
    interface: str,
    description: str,
    input_type: str,
    output_type: str,
    sources: tuple[SourceSymbolReference, ...],
) -> LibraryFunction:
    return LibraryFunction(
        library="question_table_goal",
        function_id=function_id,
        interface=interface,
        description=description,
        implementation=None,
        source_symbols=sources,
        input_type=input_type,
        output_type=output_type,
        effect="Operates on the one run-global transactional question-table Goal.",
        failure_contract=(
            "Reference-only until EpisodeBuilder ports the pinned symbols into "
            "the neutral question-table boundary; execution fails before launch."
        ),
        provenance={
            "state_ownership": "one mutable table authority per workflow",
            "scope_semantics": "read-only EpisodeGoal view over global state",
            "numerical_boundary": "accepted identities and channels only",
        },
    )


RESULT_COLUMN_SCHEMA = LibraryFunction(
    library="question_table_goal",
    function_id="result_column_schema",
    interface="goal.question_table.result_column_schema",
    description=(
        "Project the table contract's ordered result-channel IDs to the "
        "credit assignment's positional schema with an explicit zero reference."
    ),
    implementation=FunctionImplementation(
        module="question_table_goal_library.contracts",
        symbol="result_column_schema",
        is_async=False,
    ),
    input_type="question_table_goal_library.QuestionTableContractRef",
    output_type="numeric_control_library.credit_assignment.ResultColumnSchema",
    effect="Pure projection; channel order is preserved and no channel is inferred.",
    failure_contract="Rejects any value that is not the admitted table contract.",
    provenance={
        "channel_source": "QuestionTableContractRef.result_channel_ids",
        "reference_point": "explicit zero vector",
    },
)


OPEN_QUESTION_TABLE_GOAL = _definition(
    function_id="open_question_table_goal",
    interface="goal.question_table.open",
    description="Open the workflow's sole typed table store and Goal transaction.",
    input_type="question-table contract, evidence registry, and seed rows",
    output_type="run-global QuestionTableGoalState",
    sources=(
        _symbol(_TABLES, "TypedTableStore"),
        _symbol(_BINDING, "TableGoalState"),
    ),
)

SCOPE_QUESTION_TABLE_GOAL = _definition(
    function_id="scope_question_table_goal",
    interface="goal.question_table.scope",
    description="Resolve a read-only local view without creating another store.",
    input_type="QuestionTableGoalState and method_loop.EpisodeGoal",
    output_type="ScopedQuestionTableGoalView",
    sources=(
        _symbol(_BINDING, "TableGoalState"),
        _symbol(_BINDING, "TableGoalView"),
    ),
)

PROJECT_GOAL_PROMPT = _definition(
    function_id="project_goal_prompt",
    interface="goal.question_table.prompt_projection",
    description="Project immutable contract and current deficits for a local prompt.",
    input_type="ScopedQuestionTableGoalView",
    output_type="prompt artifact reference",
    sources=(
        _symbol(_BINDING, "TableGoalView.columns_by_table"),
        _symbol(_BINDING, "TableGoalView.rows_by_name"),
    ),
)

PROJECT_DIRECT_EVIDENCE_CANDIDATES = _definition(
    function_id="project_direct_evidence_candidates",
    interface="goal.question_table.direct_candidates",
    description="Project source-grounded records into direct table candidates.",
    input_type="scoped view, source artifacts, and extracted records",
    output_type="TableResultProposal",
    sources=(_symbol(_BINDING, "TableGoalState.assertion_candidates"),),
)

PROJECT_BEST_GUESS_EVIDENCE_CANDIDATES = _definition(
    function_id="project_best_guess_evidence_candidates",
    interface="goal.question_table.best_guess_candidates",
    description="Project evidence-anchored best-guess sidecar candidates.",
    input_type="scoped view, source artifacts, records, and resolutions",
    output_type="TableResultProposal",
    sources=(_symbol(_BINDING, "TableGoalState.best_guess_candidates"),),
)

PROPOSE_TABLE_RESULTS = _definition(
    function_id="propose_table_results",
    interface="goal.question_table.proposal",
    description="Create the neutral proposal consumed by GoalState.preview.",
    input_type="scoped view, record artifacts, evidence commit, and status",
    output_type="method_loop.GoalProposal[TableResultProposal]",
    sources=(
        _symbol(_BINDING, "TableGoalCandidate"),
        _symbol(_BINDING, "TableGoalState.preview"),
    ),
)

PROJECT_ACCEPTED_IDENTITY_CHANNELS = _definition(
    function_id="project_accepted_identity_channels",
    interface="goal.question_table.accepted_identities",
    description="Expose accepted logical identities by every declared result channel.",
    input_type="committed table Goal transition",
    output_type="AcceptedIdentityChannels",
    sources=(
        _symbol(_BINDING, "GoalTransition"),
        _symbol(_BINDING, "TableGoalState.commit"),
    ),
)

CHECKPOINT_QUESTION_TABLE_GOAL = _definition(
    function_id="checkpoint_question_table_goal",
    interface="goal.question_table.checkpoint",
    description="Serialize the global transactional Goal state.",
    input_type="QuestionTableGoalState",
    output_type="checkpoint artifact reference",
    sources=(_symbol(_BINDING, "TableGoalState.checkpoint_assignments"),),
)

RESTORE_QUESTION_TABLE_GOAL = _definition(
    function_id="restore_question_table_goal",
    interface="goal.question_table.restore",
    description="Restore the global transactional Goal before any Episode runs.",
    input_type="QuestionTableGoalState and checkpoint artifact",
    output_type="QuestionTableGoalState",
    sources=(_symbol(_BINDING, "TableGoalState.restore_assignments"),),
)


__all__ = [
    "CHECKPOINT_QUESTION_TABLE_GOAL",
    "OPEN_QUESTION_TABLE_GOAL",
    "PROJECT_ACCEPTED_IDENTITY_CHANNELS",
    "PROJECT_BEST_GUESS_EVIDENCE_CANDIDATES",
    "PROJECT_DIRECT_EVIDENCE_CANDIDATES",
    "PROJECT_GOAL_PROMPT",
    "PROPOSE_TABLE_RESULTS",
    "RESULT_COLUMN_SCHEMA",
    "RESTORE_QUESTION_TABLE_GOAL",
    "SCOPE_QUESTION_TABLE_GOAL",
]
