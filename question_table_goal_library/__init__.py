"""One global table Goal with read-only Episode-scoped views."""

from .contracts import (
    AcceptedIdentityChannels,
    QuestionTableContractRef,
    ScopedQuestionTableGoalView,
    TableEvaluationStatus,
    TableResultProposal,
    result_column_schema,
)
from .definitions import (
    CHECKPOINT_QUESTION_TABLE_GOAL,
    OPEN_QUESTION_TABLE_GOAL,
    PROJECT_ACCEPTED_IDENTITY_CHANNELS,
    PROJECT_BEST_GUESS_EVIDENCE_CANDIDATES,
    PROJECT_DIRECT_EVIDENCE_CANDIDATES,
    PROJECT_GOAL_PROMPT,
    PROPOSE_TABLE_RESULTS,
    RESULT_COLUMN_SCHEMA,
    RESTORE_QUESTION_TABLE_GOAL,
    SCOPE_QUESTION_TABLE_GOAL,
)


__all__ = [
    "AcceptedIdentityChannels",
    "CHECKPOINT_QUESTION_TABLE_GOAL",
    "OPEN_QUESTION_TABLE_GOAL",
    "PROJECT_ACCEPTED_IDENTITY_CHANNELS",
    "PROJECT_BEST_GUESS_EVIDENCE_CANDIDATES",
    "PROJECT_DIRECT_EVIDENCE_CANDIDATES",
    "PROJECT_GOAL_PROMPT",
    "PROPOSE_TABLE_RESULTS",
    "QuestionTableContractRef",
    "RESULT_COLUMN_SCHEMA",
    "RESTORE_QUESTION_TABLE_GOAL",
    "SCOPE_QUESTION_TABLE_GOAL",
    "ScopedQuestionTableGoalView",
    "TableEvaluationStatus",
    "TableResultProposal",
    "result_column_schema",
]
