"""Page Episode: choose a content Episode or process direct Page material."""

from handoff_library import ADMIT_PARENT_REQUEST, HandoffPayloadContract
from llm_call_library import (
    ModelTier,
    PROBABILITY_VECTOR_JUDGMENT,
    STRUCTURED_JSON_COMPLETION,
)
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
    PROJECT_BEST_GUESS_EVIDENCE_CANDIDATES,
    PROJECT_DIRECT_EVIDENCE_CANDIDATES,
    PROJECT_GOAL_PROMPT,
    PROPOSE_TABLE_RESULTS,
    RESULT_COLUMN_SCHEMA,
    SCOPE_QUESTION_TABLE_GOAL,
)

from .models import EpisodeLibraryDesign
from .lexical_probe import (
    REQUEST_PAYLOAD_CONTRACT as LEXICAL_PROBE_REQUEST_PAYLOAD_CONTRACT,
    RESULT_PAYLOAD_CONTRACT as LEXICAL_PROBE_RESULT_PAYLOAD_CONTRACT,
)
from .provenance import source_function, source_symbol
from .report import (
    REQUEST_PAYLOAD_CONTRACT as REPORT_REQUEST_PAYLOAD_CONTRACT,
    RESULT_PAYLOAD_CONTRACT as REPORT_RESULT_PAYLOAD_CONTRACT,
)
from .source_table import (
    REQUEST_PAYLOAD_CONTRACT as SOURCE_TABLE_REQUEST_PAYLOAD_CONTRACT,
    RESULT_PAYLOAD_CONTRACT as SOURCE_TABLE_RESULT_PAYLOAD_CONTRACT,
)


_BINDING_PATH = "question_pipeline/episode_binding/page_binding.py"
_LEXICAL_PATH = "question_pipeline/episode_binding/lexical_probe_binding.py"
_PROVIDER_PATH = "question_pipeline/episode_binding/provider_binding.py"
_REPORT_PATH = "question_pipeline/episode_binding/report_binding.py"
_SEARCH_PATH = "question_pipeline/utilities/search.py"
_SOURCE_TABLE_PATH = "question_pipeline/episode_binding/source_table_binding.py"
_WEB_SEARCH_PATH = "question_pipeline/episode_binding/web_search_binding.py"

UNCERTAINTY_ALPHA = 0.05
STOP_WHEN_PREDICTED_CREDIT_UPPER_AT_MOST = 0.01

REQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract(
    artifact_roles=("goal_scope", "unit"),
    required_artifact_roles=("goal_scope", "unit"),
)
RESULT_PAYLOAD_CONTRACT = HandoffPayloadContract()

CONTENT_ASSESSMENT_SYSTEM_PROMPT = (
    "Judge supplied Page content windows against declared information needs. "
    "Return named probabilities only; never select a child or decide continuation."
)

CONTENT_ASSESSMENT_PROMPT = """PAGE GOAL:
{goal_json}

PAGE CONTEXT:
{page_context_json}

DECLARED INFORMATION NEEDS:
{information_needs_json}

CANDIDATE WINDOWS:
{candidate_windows_json}

For every named window-and-need question, judge whether the candidate window
could contribute source evidence for that specific information need when
interpreted with the supplied page context. A window need not contain a
complete output row or repeat subject identity stated elsewhere on the page.

True means the window contains a reported value, estimate basis, subject
identity, relationship, label, or context that could help satisfy the need.
False means it cannot contribute even with the supplied page context."""

CHILD_SELECTION_SYSTEM_PROMPT = (
    "You choose one child from a supplied Page-child catalog. Return one JSON "
    "object. Never decide whether acquisition continues."
)

CHILD_SELECTION_PROMPT = """PAGE EPISODE GOAL:
{goal_json}

CURRENT GOAL STATE:
{goal_state_json}

PAGE SUMMARY PREPARED WHEN THIS EPISODE OPENED:
{page_summary_json}

ASSESSMENTS OF UNPROCESSED TABLES AND PROSE CHUNKS:
{content_assessment_json}

VALID CHILDREN ON THIS PULL:
{valid_children_json}

PREVIOUS CHILDREN AND THEIR MEASURED RESULTS:
{previous_children_json}

Choose exactly one option_id from VALID CHILDREN. The Page's numerical
controller has already decided that another child may be attempted. Choose
which child to try; never decide whether the Page continues or stops. Option
IDs shown only in PREVIOUS CHILDREN are consumed and unavailable.

A source_table option exists only for a table region actually detected in this
page. Never manufacture one.

A report option reads remaining prose in document order with compact
source-linked memory. Choose it when useful pieces are distributed across
chunks or isolated chunks would lose their relationships.

A lexical_probe option ranks remaining prose chunks. When choosing it, write
one literal query containing document-native words, units, labels, names,
dates, or codes likely to occur in useful text. Use prior measured results to
refine productive wording and avoid repeating wording that yielded nothing.

Assessment probabilities are planning evidence. They do not select a child,
admit evidence, assign credit, or decide continuation.

Return exactly:
{{
  "option_id": "one exact option_id from VALID CHILDREN",
  "query": "required for lexical_probe; otherwise empty",
  "objective": "the Goal information this child should seek",
  "rationale": "how page context, Goal gaps, and prior outcomes support this choice"
}}"""

CHILD_CORRECTION_PROMPT = """INVALID PAGE-CHILD PROPOSAL:
{invalid_proposal_json}

VALIDATION ERROR:
{validation_error}

CURRENTLY VALID CHILDREN:
{valid_children_json}

Correct only the structured proposal. Select one different exact option_id
from CURRENTLY VALID CHILDREN. Preserve a useful objective where the selected
option can pursue it. A lexical_probe requires a non-empty literal query.
Return one JSON object and nothing else."""

BEST_GUESS_SYSTEM_PROMPT = (
    "Infer only evidence-supported best-guess sidecar values for supplied table "
    "tasks. Return one JSON object; reported values are never overwritten."
)

BEST_GUESS_PROMPT = """QUESTION:
{question}

BEST-GUESS OPERATOR:
{operator}

MISSING ROW-SLOT TASKS:
{tasks_json}

LOCAL EVIDENCE:
{evidence_json}

For each task, infer the requested sidecar value only if local evidence and
the task's row values support it. Return no candidate when evidence is
ambiguous or irrelevant. Preserve the qualifier grain implied by evidence and
explain the exact basis without outside knowledge.

Return exactly:
{{
  "candidates": [
    {{
      "task_id": "matching task id",
      "value": "inferred sidecar value or null",
      "confidence": 0.0,
      "basis": "short evidence-grounded reason",
      "source_ids": ["existing source ids"],
      "source_chunks": ["existing source chunks"]
    }}
  ]
}}"""


OPEN_PAGE_SOURCE = source_function(
    function_id="open_page_source",
    interface="episode.unit_source",
    description=(
        "Open the Page's child planner or its one-unit material Leaf from the "
        "acquired provider result."
    ),
    input_type="Page request, acquired provider result, scoped Goal, and collaborators",
    output_type="Page UnitSource",
    sources=(
        (_BINDING_PATH, "PageBinding._make_page_item"),
        (_BINDING_PATH, "PageChildProposer"),
        (_BINDING_PATH, "PageBinding._leaf_page_episode"),
    ),
    effect="Selects the source shape from persisted acquisition facts.",
    failure_contract="Never creates a content child absent from the acquired Page.",
)

DIRECT_MATERIAL_LEAF = source_function(
    function_id="direct_material_leaf",
    interface="episode.internal_leaf_route",
    description="Compose the Page's direct one-unit material Leaf route.",
    input_type="PageUnit, Page Goal, and fetch/extract/accept/result functions",
    output_type="one-unit Page Leaf source",
    sources=(
        (_BINDING_PATH, "PageBinding._make_page_leaf"),
        (_BINDING_PATH, "PageBinding._material_leaf"),
        (_BINDING_PATH, "PageBinding._material_page_episode"),
        (_BINDING_PATH, "PageBinding._leaf_page_episode"),
    ),
    effect="Keeps fallback Page material inside the Page Episode boundary.",
    failure_contract="A material Leaf cannot open a nested content Episode.",
)

FETCH_EXTRACT_PAGE_MATERIAL = source_function(
    function_id="fetch_extract_page_material",
    interface="evidence.extraction",
    description="Acquire and extract one Page into typed PageMaterial.",
    input_type="PageUnit",
    output_type="PageMaterial",
    sources=((_BINDING_PATH, "PageBinding.fetch_extract"),),
    effect="Acquires the declared Page and retains its typed fate and provenance.",
    failure_contract="Acquisition or extraction failure remains a typed Page fate.",
)

ACCEPT_PAGE_MATERIAL = source_function(
    function_id="accept_page_material",
    interface="evidence.acceptance",
    description="Commit exact Page evidence before a Goal proposal is previewed.",
    input_type="PageUnit and PageMaterial",
    output_type="evidence-linked PageMaterial",
    sources=((_BINDING_PATH, "PageBinding.accept_evidence"),),
    effect="Uses the durable evidence registry as the acceptance boundary.",
    failure_contract="A value without a complete accepted source chain mints no identity.",
)

PROJECT_PAGE_MATERIAL_RESULT = source_function(
    function_id="project_page_material_result",
    interface="goal.question_table.proposal",
    description="Project accepted PageMaterial to one table Goal proposal.",
    input_type="PageUnit and accepted PageMaterial",
    output_type="method_loop.GoalProposal",
    sources=((_BINDING_PATH, "PageBinding._page_result"),),
    effect="Presents accepted material to the one run-global Goal transaction.",
    failure_contract="Carries no direct write capability and commits nothing itself.",
)


ASSESS_PAGE_CONTENT = source_function(
    function_id="assess_page_content",
    interface="assessment.window_matrix",
    description="Fit Page windows and aggregate per-need probabilities once.",
    input_type="Page context, information needs, candidates, and vector judge",
    output_type="PageContentAssessment",
    sources=((_BINDING_PATH, "assess_page_content"),),
    effect="Creates planning measurements without selecting a child.",
    failure_contract="Assessment failure remains distinct from irrelevant content.",
)

ADMIT_PAGE_CHILD = source_function(
    function_id="admit_page_child",
    interface="llm.response_admission",
    description="Admit one exact available child option and required probe query.",
    input_type="structured JSON response and valid child catalog",
    output_type="PageChildProposal",
    sources=(
        (_BINDING_PATH, "_page_child_proposal_from_payload"),
        (_BINDING_PATH, "propose_page_child"),
    ),
    effect="Validates selection without assigning credit or continuation.",
    failure_contract="One semantic correction is allowed, then rejection is explicit.",
)

ADMIT_BEST_GUESSES = source_function(
    function_id="admit_page_best_guesses",
    interface="llm.response_admission",
    description="Admit task-matched evidence-linked best-guess candidates only.",
    input_type="structured JSON response, task catalog, and local evidence",
    output_type="best-guess candidate records",
    sources=((_SEARCH_PATH, "infer_best_guess_candidates"),),
    effect="Produces sidecar candidates; it never changes reported cells.",
    failure_contract="Ambiguous, unmatched, or source-free candidates are rejected.",
)

PAGE_CHILD_SOURCE = source_function(
    function_id="page_child_source",
    interface="episode.unit_source",
    description="Expose valid content children and pull the selected Episode.",
    input_type="Page state, assessments, Goal view, and measured child history",
    output_type="content child proposal or source exhaustion",
    sources=((_BINDING_PATH, "PageChildProposer"),),
    effect="Consumes exactly one declared content option per pull.",
    failure_contract="Never fabricates a table region or reopens a consumed option.",
)

BUILD_SOURCE_TABLE = source_function(
    function_id="build_source_table",
    interface="episode.child_builder",
    description="Build the selected source-table Episode.",
    input_type="typed source-table ParentRequest",
    output_type="question_pipeline.source_table Episode",
    sources=(
        (_BINDING_PATH, "PageChildProposer.next"),
        (_SOURCE_TABLE_PATH, "SourceTableBinding._make_source_table_episode"),
    ),
    effect="Constructs one source-table child with its own Goal, controller, and loop.",
    failure_contract="Rejects an unavailable table region or mismatched Goal lineage.",
)

BUILD_REPORT = source_function(
    function_id="build_report",
    interface="episode.child_builder",
    description="Build the selected ordered-report Episode.",
    input_type="typed report ParentRequest",
    output_type="question_pipeline.report Episode",
    sources=(
        (_BINDING_PATH, "PageChildProposer.next"),
        (_REPORT_PATH, "ReportBinding._make_report_episode"),
    ),
    effect="Constructs one report child with its own Goal, controller, and loop.",
    failure_contract="Rejects absent prose or mismatched Goal lineage.",
)

BUILD_LEXICAL_PROBE = source_function(
    function_id="build_lexical_probe",
    interface="episode.child_builder",
    description="Build the selected lexical-probe Episode.",
    input_type="typed lexical-probe ParentRequest",
    output_type="question_pipeline.lexical_probe Episode",
    sources=(
        (_BINDING_PATH, "PageChildProposer.next"),
        (_LEXICAL_PATH, "LexicalProbeBinding._make_probe_episode"),
    ),
    effect="Constructs one lexical probe with its own Goal, controller, and loop.",
    failure_contract="Rejects an empty query, absent prose, or mismatched Goal lineage.",
)

PREPARE_CONTENT_REQUEST = source_function(
    function_id="prepare_page_content_request",
    interface="handoff.parent_request_projection",
    description="Project only selected content, objective, and scoped artifact IDs.",
    input_type="Page state, selected option, and child identity",
    output_type="handoff_library.ParentRequest",
    sources=((_BINDING_PATH, "PageChildProposer.next"),),
    effect="Creates the closed request owned by the Page-content edge.",
    failure_contract="Rejects unknown interface, artifact, measurement, state, and flag roles.",
)

RECEIVE_CONTENT_RESULT = source_function(
    function_id="receive_page_content_result",
    interface="handoff.child_result_projection",
    description="Admit one content result and project identities for Page-local credit.",
    input_type="Page state, matching request, ChildResult, and EpisodeCompletion",
    output_type="CreditObservation on the Page scale",
    sources=((_BINDING_PATH, "PageBinding._on_page_child"),),
    effect="Checks correlation and recomputes the parent-local identity vector.",
    failure_contract="Rejects cross-wired results and never reads child prose artifacts.",
)

BUILD_PAGE_RESULT = source_function(
    function_id="build_page_result",
    interface="handoff.child_result_builder",
    description="Build the Page Episode's closed result for its Search parent.",
    input_type="completed Page state and matching ParentRequest",
    output_type="handoff_library.ChildResult",
    sources=(
        (_BINDING_PATH, "PageBinding._leaf_page_episode"),
        (_WEB_SEARCH_PATH, "WebSearchBinding._page_episode_result"),
        (_PROVIDER_PATH, "ProviderRuntime._episode_result"),
    ),
    effect="Returns identities by channel, measurements, flags, and artifact IDs.",
    failure_contract="Never returns page text, model output, or prompt rationales upward.",
)


BINDING = EpisodeBindingDeclaration(
    grain_name="page",
    interface="question_pipeline.page",
    topology_role=EpisodeTopologyRole.BRANCH,
    goal="one acquired Page and the information needs inherited from its Search Goal",
    unit="one selected Page-content Episode or one direct Page-material Leaf",
    result="Page-local accepted table identities and provenance artifacts",
    progress=(
        "marginal dominated hypervolume over accepted stable identities kept "
        "distinct by declared result channel"
    ),
    stopping=(
        "continue while the upper uncertainty bound on predicted next marginal "
        "hypervolume exceeds the declared tolerance"
    ),
    admit_request=ADMIT_PARENT_REQUEST.bind(
        "admit_page_request",
        arguments={"payload_contract": REQUEST_PAYLOAD_CONTRACT.as_record()},
    ),
    open_source=OPEN_PAGE_SOURCE.bind("open_page_source"),
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
    build_result=BUILD_PAGE_RESULT.bind(
        "build_page_result",
        arguments={"payload_contract": RESULT_PAYLOAD_CONTRACT.as_record()},
    ),
    components=(
        SCOPE_QUESTION_TABLE_GOAL.bind("scope_goal"),
        PROJECT_GOAL_PROMPT.bind("project_goal_prompt"),
        DIRECT_MATERIAL_LEAF.bind("direct_material_leaf"),
        FETCH_EXTRACT_PAGE_MATERIAL.bind("fetch_extract_material"),
        ACCEPT_PAGE_MATERIAL.bind("accept_material"),
        PROJECT_PAGE_MATERIAL_RESULT.bind("project_material_result"),
        PAGE_CHILD_SOURCE.bind("open_child_planner"),
        PROBABILITY_VECTOR_JUDGMENT.bind(
            "judge_content_windows",
            arguments={
                "tier": ModelTier.FAST.value,
                "system_prompt": CONTENT_ASSESSMENT_SYSTEM_PROMPT,
                "prompt_template": CONTENT_ASSESSMENT_PROMPT,
            },
        ),
        ASSESS_PAGE_CONTENT.bind("assess_content"),
        STRUCTURED_JSON_COMPLETION.bind(
            "propose_child",
            arguments={
                "tier": ModelTier.FAST.value,
                "system_prompt": CHILD_SELECTION_SYSTEM_PROMPT,
                "prompt_template": CHILD_SELECTION_PROMPT,
                "correction_prompt_template": CHILD_CORRECTION_PROMPT,
            },
        ),
        ADMIT_PAGE_CHILD.bind("admit_child_proposal"),
        STRUCTURED_JSON_COMPLETION.bind(
            "infer_best_guess",
            arguments={
                "tier": ModelTier.REASONING.value,
                "system_prompt": BEST_GUESS_SYSTEM_PROMPT,
                "prompt_template": BEST_GUESS_PROMPT,
            },
        ),
        ADMIT_BEST_GUESSES.bind("admit_best_guesses"),
        PROJECT_DIRECT_EVIDENCE_CANDIDATES.bind("project_direct_candidates"),
        PROJECT_BEST_GUESS_EVIDENCE_CANDIDATES.bind(
            "project_best_guess_candidates"
        ),
        PROPOSE_TABLE_RESULTS.bind("propose_table_results"),
    ),
    child_slots=(
        EpisodeChildSlot(
            name="source_table",
            accepted_interfaces=("question_pipeline.source_table",),
            build_child=BUILD_SOURCE_TABLE.bind("build_source_table"),
            prepare_request=PREPARE_CONTENT_REQUEST.bind(
                "prepare_source_table_request",
                arguments={
                    "payload_contract": (
                        SOURCE_TABLE_REQUEST_PAYLOAD_CONTRACT.as_record()
                    )
                },
            ),
            receive_result=RECEIVE_CONTENT_RESULT.bind(
                "receive_source_table_result",
                arguments={
                    "payload_contract": (
                        SOURCE_TABLE_RESULT_PAYLOAD_CONTRACT.as_record()
                    )
                },
            ),
        ),
        EpisodeChildSlot(
            name="report",
            accepted_interfaces=("question_pipeline.report",),
            build_child=BUILD_REPORT.bind("build_report"),
            prepare_request=PREPARE_CONTENT_REQUEST.bind(
                "prepare_report_request",
                arguments={
                    "payload_contract": REPORT_REQUEST_PAYLOAD_CONTRACT.as_record()
                },
            ),
            receive_result=RECEIVE_CONTENT_RESULT.bind(
                "receive_report_result",
                arguments={
                    "payload_contract": REPORT_RESULT_PAYLOAD_CONTRACT.as_record()
                },
            ),
        ),
        EpisodeChildSlot(
            name="lexical_probe",
            accepted_interfaces=("question_pipeline.lexical_probe",),
            build_child=BUILD_LEXICAL_PROBE.bind("build_lexical_probe"),
            prepare_request=PREPARE_CONTENT_REQUEST.bind(
                "prepare_lexical_probe_request",
                arguments={
                    "payload_contract": (
                        LEXICAL_PROBE_REQUEST_PAYLOAD_CONTRACT.as_record()
                    )
                },
            ),
            receive_result=RECEIVE_CONTENT_RESULT.bind(
                "receive_lexical_probe_result",
                arguments={
                    "payload_contract": (
                        LEXICAL_PROBE_RESULT_PAYLOAD_CONTRACT.as_record()
                    )
                },
            ),
        ),
    ),
)

DESIGN = EpisodeLibraryDesign(
    qualified_name="question_pipeline.page",
    title="Page content planner",
    binding=BINDING,
    function_definitions=(
        ADMIT_PARENT_REQUEST,
        OPEN_PAGE_SOURCE,
        RESULT_COLUMN_SCHEMA,
        COMPOSE_INCIDENCE_CONTROLLER,
        MARGINAL_DOMINATED_HYPERVOLUME,
        PAIRED_INCIDENCE,
        PREDICTED_CREDIT_UPPER_BOUND,
        BUILD_PAGE_RESULT,
        SCOPE_QUESTION_TABLE_GOAL,
        PROJECT_GOAL_PROMPT,
        DIRECT_MATERIAL_LEAF,
        FETCH_EXTRACT_PAGE_MATERIAL,
        ACCEPT_PAGE_MATERIAL,
        PROJECT_PAGE_MATERIAL_RESULT,
        PAGE_CHILD_SOURCE,
        PROBABILITY_VECTOR_JUDGMENT,
        ASSESS_PAGE_CONTENT,
        STRUCTURED_JSON_COMPLETION,
        ADMIT_PAGE_CHILD,
        ADMIT_BEST_GUESSES,
        PROJECT_DIRECT_EVIDENCE_CANDIDATES,
        PROJECT_BEST_GUESS_EVIDENCE_CANDIDATES,
        PROPOSE_TABLE_RESULTS,
        BUILD_SOURCE_TABLE,
        BUILD_REPORT,
        BUILD_LEXICAL_PROBE,
        PREPARE_CONTENT_REQUEST,
        RECEIVE_CONTENT_RESULT,
    ),
    source_symbols=(
        source_symbol(_BINDING_PATH, "PageBinding"),
        source_symbol(_BINDING_PATH, "PageChildProposer"),
        source_symbol(_BINDING_PATH, "assess_page_content"),
        source_symbol(_BINDING_PATH, "propose_page_child"),
    ),
)


__all__ = [
    "BEST_GUESS_PROMPT",
    "BINDING",
    "CHILD_SELECTION_PROMPT",
    "CONTENT_ASSESSMENT_PROMPT",
    "DESIGN",
    "REQUEST_PAYLOAD_CONTRACT",
    "RESULT_PAYLOAD_CONTRACT",
]
