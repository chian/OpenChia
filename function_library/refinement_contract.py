"""The shared, fixed shape of the refinement Episodes—not a workflow engine."""

from dataclasses import dataclass
from types import MappingProxyType

from handoff_library import HandoffPayloadContract


@dataclass(frozen=True)
class RefinementRole:
    title: str
    goal: str
    unit: str
    progress: str
    children: tuple[str, ...]
    instructions: str


ROLES = MappingProxyType({
    "parts": RefinementRole(
        "RefineParts",
        "Make the assigned whole satisfy its original requirements.",
        "Select a behavioral problem, obtain a child result, and assess its contribution to the whole.",
        "New independently measured whole-scope evidence or admitted coordination knowledge.",
        ("parts", "designer", "support", "question", "measure", "verify"),
        "Choose work from measured gaps and shared regression history, not the Target Workflow's file or Episode tree. "
        "Use the Builder handoff's requirement identities, prerequisites and recorded baseline. Its static "
        "passes are existing achievement, not new credit or proof of behavior; retain behavioral coverage gaps. "
        "You alone may assign Designers or a proper smaller Parts scope. Combine coupled problems when "
        "repairs conflict; preserve both original requirements and their evidence. A new child is not progress. "
        "Use current prerequisite_assessments to avoid repeating resolved questions or measure work; "
        "these are decision evidence, not proof that the implementation passes. "
        "Use evaluation_availability and child_decisions to address missing measurement prerequisites. "
        "Route original measurement requests with assignment prerequisite_refs; their specifications are "
        "reference data, not expanded edit scope or approval to create another workflow. "
        "At the root, whole_build_readiness covers every mandatory requirement and preservation guard; "
        "use its gaps to select unfinished work. Child completion does not establish whole-build acceptance. "
        "An unavailable evaluation is not a failing behavior check or permission to change active criteria. "
        "For replacement work, name the returned_assignments in supersedes_assignment_refs. Retain their "
        "requirements, slices and protections; an admitted stronger measure cannot discard old checks. "
        "Read predecessor_reports as original evidence, not as proof of current acceptance.",
    ),
    "designer": RefinementRole(
        "DesignPart",
        "Design and realize a working solution to the assigned behavioral problem.",
        "Admit an approach and local measure, obtain implementation, then independently verify the part.",
        "Evidence-backed improvement under the part's acceptance contract, not design prose.",
        ("implementer", "support", "question", "measure", "verify"),
        "Own the approach through implementation and independent acceptance. Ground the local coding measure "
        "in the assigned requirements before coding. You may request a named prerequisite, but cannot create "
        "another Designer or Parts scope. Use the admitted measures and current prerequisite_assessments "
        "returned by your children; they do not replace independent acceptance. "
        "Read child_decisions and evaluation_availability before repeating an unavailable check. "
        "Keep assigned_prerequisites as original evidence when planning preparation; instrument coding "
        "still requires an admitted plan, grounded local measure and authorized paths. "
        "A different acceptance contract needs a successor assignment from your owner. "
        "When a new plan replaces a returned Implementer, include its assignment reference in the "
        "design proposal's supersedes_assignment_refs. Its prior evidence and measures remain available; "
        "repeating an old pass under a new measure identity is not new progress. "
        "Return cross-part problems to your Parts owner with evidence.",
    ),
    "implementer": RefinementRole(
        "RefineImplementation",
        "Make scoped candidate changes that satisfy the parent's fixed implementation measure.",
        "Propose one scoped change and measure the resulting exact candidate.",
        "New measured implementation improvement with required regression guards.",
        ("question",),
        "Implement the admitted design. Change only assigned paths and permitted specification details. "
        "Respect source_kinds: raw_model_source and candidate_raw_source are before host declaration attachment; emitted_module "
        "contains its original host-owned declaration, which is not editable. After an authorized "
        "plan-detail revision the host reattaches the current declaration during source admission. "
        "Plan edits must use candidate_materialization.permitted_detail_edits and exact before values. "
        "Each instrument_builds entry supplies separately authorized checker paths and its own "
        "candidate_materialization.permitted_detail_edits. Use those exact namespaced targets for "
        "checker plans through the same edit operation; never apply primary-build targets to a checker. Editing a checker does not make "
        "its source an accepted oracle or let you replace the measures judging this assignment. "
        "whole-node targets take the Builder's planner-choice object, not host identities. A missing node "
        "uses before=null and can only fill an already-approved Episode. Repair child payload/interface "
        "and parent child_slots together within the assigned scope; otherwise ask the owner for coordinated work. "
        "Copy architecture_owned_bindings exactly. Do not include approved repeatable calls in child_slots "
        "or replace their bindings; the host installs them. "
        "leave implementation_detail_operations empty when only source needs changing. "
        "Use the supplied local measure; never edit acceptance criteria to make a repair pass. A patch, "
        "restored old pass, or failed attempt earns no credit by itself. Escalate an inadequate assignment.",
    ),
    "support": RefinementRole(
        "FindDesignSupport",
        "Fill the caller's named guidance gap using applicable source-linked library material.",
        "Select and assess a focused package of instructions or examples for the named need.",
        "New admitted coverage of the guidance gap, not retrieved volume.",
        (),
        "Return only relevant guidance with source identity, applicability, limitations and missing coverage. "
        "Examples are not proof and cannot change the caller's authority or judgment contract. "
        "Select checks from the parent's investigation_needs. The host determines applicability from "
        "their actual observations; you do not author the accepted finding or its decision effect.",
    ),
    "question": RefinementRole(
        "ResolveQuestion",
        "Resolve an uncertainty that changes the caller's next decision.",
        "Propose a discriminating observation and assess its admitted evidence.",
        "A supported decision-relevant distinction, including a supported negative answer.",
        (),
        "Use the named question and supplied evidence. Identify the observation that separates alternatives. "
        "Select its checks from investigation_needs; the host maps observations to the parent's fixed "
        "decision meanings. When check_design.assigned_review_ref is supplied, instead review that exact "
        "definition against the original requirements and return check_review for every fixed criterion. "
        "Challenge the expected results, control polarities, observation relevance and limitations. "
        "Reject self-confirming or irrelevant tests even if their controls would execute successfully. "
        "Your review is a judgment, not target success, executable evidence or credit. Preserve unresolved limitations.",
    ),
    "measure": RefinementRole(
        "EstablishMeasure",
        "Establish an adequate instrument for the caller's original requirement.",
        "Propose an instrument and examine whether it rejects specified incorrect or trivial outcomes.",
        "New demonstrated adequacy of the instrument, not the number of assertions.",
        ("question",),
        "Derive expected behavior from the requirement, not the candidate implementation. Supply grounding "
        "and negative controls. You cannot certify your own instrument by assertion. Route required code "
        "changes back through the owner; do not create a Designer yourself. "
        "When measure_needs identifies missing authority/grounding or an authorized instrument-building "
        "specification, return its exact need_key using prerequisite_request. This is an unresolved "
        "request to your owner, not progress, a usable instrument or permission to change its criteria. "
        "When instrument_returns offers an independently accepted checking build, include its exact "
        "spec_ref/report_ref/source_ref as instrument_return in your instrument proposal. Keep the "
        "original oracle_ref, grounded cases, controls and limitations; the host binds the accepted "
        "source and runs the same executable adequacy controls. A successful build does not itself "
        "admit a measure or alter an active assignment. grounding_acquisitions lists explicitly authorized "
        "question/source routes and fixed case templates. Use ResolveQuestion for a missing result; "
        "then select its exact acquired_grounding references in the instrument proposal. Keep the "
        "template's original criterion and oracle fields. The host fills expected values and controls "
        "from the independent evidence. When check_design is available, you may design a new check "
        "using its registered predicates and authorized execution bindings. Submit check_design with "
        "requirement-based reasoning, expected observations, justified satisfactory/violating controls "
        "and explicit limitations. A separate Question child reviews the immutable proposal. After "
        "its return, select reviewed_definition_ref to submit it to host control execution and admission; "
        "revise any rejected design. You cannot review your own proposal, award credit, or equate "
        "agreement with target correctness. If neither design nor acquisition is authorized, return "
        "the original grounding_required request.",
    ),
    "verify": RefinementRole(
        "VerifyBehavior",
        "Independently determine whether the exact candidate satisfies the parent's requirements.",
        "Execute the assigned acceptance checks and return evidence, counterexamples and limitations.",
        "New operative verification evidence; a favorable verdict is not inherently rewarded.",
        (),
        "Evaluate the exact candidate against the parent's unchanged acceptance contract. Do not repair "
        "the target or weaken the checks. A grounded failing determination is a useful result, not a "
        "reason to hide the failure or claim that the repair was accepted.",
    ),
})

CHILDREN = MappingProxyType({name: role.children for name, role in ROLES.items()})
DISPOSITIONS = (
    "continuing",
    "attained",
    "yield_exhausted_unresolved",
    "needs_parent_decision",
    "blocked",
    "interrupted",
    "cancelled",
    "invalid",
)
REQUEST_PAYLOAD = HandoffPayloadContract(
    artifact_roles=("campaign", "assignment", "invocation"),
    required_artifact_roles=("campaign", "assignment", "invocation"),
)
RESULT_PAYLOAD = HandoffPayloadContract(
    artifact_roles=("report",),
    required_artifact_roles=("report",),
    state_values={"disposition": DISPOSITIONS[1:]},
    required_state_names=("disposition",),
)

# One transport for every refinement role. Evaluation uses the existing Run
# executor; neither this protocol nor an Episode provides a replay/test runner.
OPERATIONS = frozenset({
    "context",
    "begin_unit",
    "propose",
    "prepare_child",
    "enter_child",
    "receive_child",
    "evaluate",
    "close_unit",
    "report",
})
