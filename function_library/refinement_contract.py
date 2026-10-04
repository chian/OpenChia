"""The shared, fixed shape of the refinement Episodes—not a workflow engine."""

from dataclasses import dataclass
from types import MappingProxyType

from handoff_library import HandoffPayloadContract
from method_loop import ReportContract


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
        "Choose a behavioral problem from measurements, evaluation_availability and child_reports. "
        "Each requirement is named by its location in the approved specification. Static passes "
        "establish materialization only; behavioral requirements retain their own coverage. "
        "Assign a Designer or a proper smaller Parts scope for coupled work, preserving the original "
        "requirements and protections. Each assignment inherits the established local and acceptance "
        "measurements. EstablishMeasure designs explicitly requested missing or inadequate measurements. "
        "Give every child a focused goal and a return_contract: name your next decision, the measurements "
        "and requirement locations needed for it, and the relevant findings or blockers. A Measure child "
        "normally returns measurement_findings and open_decisions; a repair child normally returns its "
        "measured changes and unresolved requirements. Follow-up verification has its own declared "
        "verification_return_contract. Select only information needed for the next decision. "
        "Use measurement outcomes and changes to distinguish new evidence, regression, stale evidence "
        "and missing measurement. Child disposition alone does not establish whole-build acceptance. "
        "For a returned open_decisions entry marked assignment_prerequisite=true, copy its "
        "kind, purpose and requirements into prerequisites. Use [] when assigning new work. "
        "These preserve the original need and grant no additional edit authority. "
        "replace_previous explicitly replaces the latest returned child of that role for that "
        "requirement scope, preserving its measurement obligations and numerical lineage. "
        "Use conflict to coordinate the named kind and requirement scope under this Parts owner. "
        "A nested Parts can forward a returned measurement need using return_prerequisite; "
        "the root retains responsibility for resolving or escalating its assigned whole.",
    ),
    "designer": RefinementRole(
        "DesignPart",
        "Design and realize a working solution to the assigned behavioral problem.",
        "Admit an approach and local measure, obtain implementation, then independently verify the part.",
        "Evidence-backed improvement under the part's acceptance contract, not design prose.",
        ("implementer", "support", "question", "measure", "verify"),
        "Own the approach through implementation and independent acceptance. Use measurements, "
        "evaluation_availability and child_reports to select the next action. The inherited local "
        "measure judges coding progress; independent acceptance retains its original requirements. "
        "Request EstablishMeasure explicitly for a focused missing or inadequate judgment, naming "
        "its purpose and requirement locations. Its report should describe admitted coverage, "
        "control outcomes, limitations and remaining needs using measurement_findings and open_decisions. "
        "Every prerequisite child receives a goal and return_contract suited to your next decision. "
        "An implementation plan maps every assigned contribution requirement to its design reasoning. "
        "Supply implementation_return_contract for local outcomes and changes, and "
        "verification_return_contract for the independent acceptance information you need. "
        "These reports remain distinct: local progress is not independent acceptance. "
        "Use replace_previous to replace your latest returned Implementer for this work. "
        "Keep earlier obligations through inherited measurements. The design input contains the "
        "latest approach, while child_reports contains the information requested from completed work. "
        "Forward an out-of-scope returned measurement need to your parent using return_prerequisite "
        "with its kind, purpose and requirement locations. Cross-part repair belongs to Parts.",
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
        "decision meanings. When check_design.review_assigned is true, instead review current_design "
        "definition against the original requirements and return check_review for every fixed criterion. "
        "Challenge the expected results, control polarities, observation relevance and limitations. "
        "Check the declared judgment purpose: a local implementation measure can establish necessary "
        "progress without replacing independent acceptance. Do not require a local pass to prove "
        "the entire workflow correct, and do not silently weaken final acceptance. Compare observable "
        "claims with the harness's available_observations; never assume a prose-described projector "
        "exists. Request/model-response/action provenance can establish the recorded selection path, "
        "not private model attention. State that distinction rather than requiring mind-reading or "
        "claiming it occurred. Unexecuted branches remain explicit limitations. "
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
        "Read measure_needs together with check_design and grounding_acquisitions. Missing pre-existing "
        "grounded cases does not mean that constructing a check is unauthorized. When reviewed check "
        "design is available, derive the check and its controls from the original requirement and "
        "supported observations, then obtain the separate review; do not return grounding_required "
        "merely because no check has been written yet. If the needed observation or authority is "
        "unavailable through those routes, or an authorized instrument must first be built, return "
        "the applicable need's kind, purpose and requirements using prerequisite_request. That is an unresolved request "
        "to your owner, not progress, a usable instrument or permission to change its criteria. "
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
        "observation paths from check_design.available_observations only. That catalog is the actual "
        "harness interface: observation_schema describes it; it cannot add a projector, summary field, "
        "stop-injection Run or other unimplemented behavior. Use verified registration fields for "
        "frozen declarations, actual typed events for what executed, and answer predicates for task "
        "correctness. Do not confuse contract equality with observed behavior or recorded model prose "
        "with host judgment. A normal Run cannot establish unexecuted failure branches; preserve that "
        "limitation explicitly rather than inventing a stop matrix. record_conditions_v1 can compare "
        "selected fields, quantify actual event arrays and delegate registered answer predicates; "
        "its full condition syntax is in predicate provenance. Controls are concrete input records "
        "for that executable predicate, not descriptions of a projector somebody must implement later. "
        "Include requirement-based reasoning, expected observations, justified satisfactory/violating controls "
        "and explicit limitations. A separate Question child reviews the immutable proposal. After "
        "its return, use submit_reviewed_design=true to submit the current design for control execution and admission; "
        "revise any rejected design. You cannot review your own proposal, award credit, or equate "
        "agreement with target correctness. If neither design nor acquisition is authorized, return "
        "the original grounding_required request. That same exact request remains available when "
        "reviewed design is authorized but the supplied observations cannot establish the assigned "
        "requirement. Do not paraphrase the same unavailable projector into another design.",
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

# Each Episode declares its working inputs. The method loop supplies child
# reports through its separate, parent-contracted communication boundary.
MODEL_INPUT_COMPONENTS = MappingProxyType({
    "parts": ("measurements", "prerequisites", "coordination"),
    "designer": ("measurements", "prerequisites", "materialization", "source", "design"),
    "implementer": ("measurements", "prerequisites", "materialization", "source", "design"),
    "measure": ("measurements", "prerequisites", "measure_design", "grounding", "investigation"),
    "question": ("measurements", "prerequisites", "measure_design", "investigation"),
    "support": ("measurements", "investigation"),
    "verify": ("measurements",),
})

INPUT_MEASUREMENTS = MappingProxyType({
    "parts": ("local", "composition"),
    "designer": ("local", "acceptance"),
    "implementer": ("local",),
    "measure": ("adequacy",),
    "question": ("question",),
    "support": ("support",),
    "verify": (),  # Its parent declares acceptance or composition.
})
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


def verification_return_contract(purpose, requirements):
    """The Parts/Designer loop's declared baseline-verification return."""
    return {
        "decision": "Which assigned requirements need work before independent acceptance?",
        "measurements": [{
            "name": "Independent requirement evaluation",
            "purpose": purpose,
            "requirements": list(requirements),
        }],
        "include": ["candidate_changes", "open_decisions"],
    }


def check_review_return_contract():
    """EstablishMeasure asks its Question child for this check-design review."""
    return {
        "decision": "Is this proposed instrument adequate to submit for control execution?",
        "measurements": [],
        "include": ["check_review", "open_decisions"],
    }


def child_report_contract(declaration):
    """Bind the refiner's requested measurements to the shared method boundary."""
    return ReportContract(
        decision=declaration["decision"],
        measurements={item["name"]: {
            "purpose": item["purpose"], "requirements": item["requirements"],
        } for item in declaration["measurements"]},
        information={
            "role": "The requested child role, to select the next kind of work.",
            "goal": "The child's assigned question or change, in meaningful text.",
            "requirements": "Original specification locations addressed by this child.",
            "return": "The parent's requested measurement outcomes and selected findings.",
        },
    )


def root_return_contract(requirements):
    """Duet's return request when starting the complete refinement workflow."""
    return {
        "decision": "Is the Target Workflow ready, and which requirements remain unresolved?",
        "measurements": [{
            "name": "Whole-workflow acceptance",
            "purpose": "composition",
            "requirements": list(requirements),
        }],
        "include": ["candidate_changes", "open_decisions"],
    }

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
