"""Apply implementation choices to the existing Builder's typed plan graph.

Only approved nodes are addressable. Graph construction remains host-owned;
the model supplies the same implementation choices as initial planning.
"""

from dataclasses import replace

from agent.duet_contracts import canonical_json
from agent.episode_contracts import Sha256Digest
from episode_builder._contract_base import BuildDeficit
from episode_builder.call_plan import materialize_call
from episode_builder.plan_choices import (
    install_architecture_bindings,
    materialize_edge_choices,
    materialize_node_choices,
    node_choices,
)
from episode_builder.planner import (
    _admit_plan_payload,
    _architecture_numeric_bindings,
    _library_functions,
)
from episode_builder.reference import EpisodeReferenceResolver
from function_library.materialization_checks import NODE_PLAN_CONSISTENCY
from function_library.models import _thaw_json


_CHECKING = BuildDeficit(
    code="candidate_plan_checking",
    field_path="node_plan",
    detail="Candidate plan is awaiting the existing native checks.",
)


def choices(plan, local_id, approved_calls):
    node = next((item for item in plan.nodes if item.local_id == local_id), None)
    if node is None:
        return None
    return node_choices(
        node,
        tuple(edge for edge in plan.edges if edge.parent_local_id == local_id),
        calls=tuple(
            call for call in approved_calls if call.caller_local_id == local_id
        ),
        unresolved=(
            {"field_path": item.field_path, "detail": item.detail}
            for item in plan.deficits
            if item.code == "design_choice_unresolved"
            and item.episode_local_id == local_id
        ),
    )


def resolve_plan_reference(design, prior=None):
    if design.episode_reference is None:
        return None
    context = EpisodeReferenceResolver().resolve(design.episode_reference)
    if prior is not None and (
        context.design.episode_id != prior.reference_episode_id
        or Sha256Digest.of_record(context.as_record()) != prior.reference_evidence_hash
    ):
        raise ValueError("plan repair cannot change the pinned reference evidence")
    return context


def _checked_plan(plan, inputs):
    # Retain current unresolved choices and authority limits. Revised nodes
    # supply their own current choices; old implementation ambiguities are not
    # permanent exclusions after those choices pass the native checks.
    preserved = {
        canonical_json(item.as_record()): item
        for item in plan.deficits
        if item.code
        in {
            "design_choice_unresolved",
            "directive_plan_scope_exceeded",
        }
    }
    checking = replace(plan, deficits=(_CHECKING,))
    checking.validate_against(inputs.build_request, inputs.build_attempt)
    nodes = {node.local_id: node for node in checking.nodes}
    deficits = list(preserved.values())
    for design in inputs.build_request.frozen_workflow.workflow.episodes:
        node = nodes.get(design.local_id)
        context = None
        if node is not None and node.reference_episode_id is not None:
            try:
                context = resolve_plan_reference(design, node)
            except (TypeError, ValueError) as exc:
                deficits.append(
                    BuildDeficit(
                        code="reference_unavailable",
                        field_path="episode_reference",
                        detail=str(exc),
                        episode_local_id=design.local_id,
                    )
                )
        result = NODE_PLAN_CONSISTENCY.load()(
            inputs.build_request,
            checking,
            design.local_id,
            reference_context=context,
        )
        deficits.extend(
            BuildDeficit.from_record(item) for item in result["diagnostics"]
        )
    # Partial typed plans can omit edges, but must never lose that incompleteness
    # just because the corresponding parent has no declared slot yet.
    connected = {(edge.parent_local_id, edge.child_local_id) for edge in plan.edges}
    for design in inputs.build_request.frozen_workflow.workflow.episodes:
        pair = (design.workflow_parent_local_id, design.local_id)
        if pair[0] is not None and pair not in connected:
            deficits.append(
                BuildDeficit(
                    code="edge_unplanned",
                    field_path="workflow_parent_local_id",
                    detail=f"no materialized edge joins {pair[0]!r} to {pair[1]!r}",
                    episode_local_id=pair[0],
                )
            )
    result = replace(checking, deficits=tuple(deficits))
    result.validate_against(inputs.build_request, inputs.build_attempt)
    return result


def revise_plan(current, inputs, proposed, changed_fields):
    """Admit one atomic batch; callers enforce exact targets and writable paths."""
    workflow = inputs.build_request.frozen_workflow.workflow
    designs = {node.local_id: node for node in workflow.episodes}
    nodes = {node.local_id: node for node in current.nodes}
    payloads = {}
    unresolved = []
    for local_id, value in proposed.items():
        design = designs[local_id]
        payload = _admit_plan_payload(_thaw_json(value))
        bindings, failure = _architecture_numeric_bindings(design)
        if failure is not None:
            raise ValueError(failure.detail)
        payload = install_architecture_bindings(payload, bindings)
        payloads[local_id] = payload
        old = nodes.get(local_id)
        new = materialize_node_choices(
            design,
            payload,
            resolve_plan_reference(design, old),
            has_children=any(
                node.workflow_parent_local_id == local_id for node in workflow.episodes
            ),
        )
        if old is not None:
            # A field edit cannot quietly drop unavailable slots while reconstructing
            # the payload of a partial plan. Only explicit slot/whole-plan edits do so.
            updates = {"module_name": old.module_name, "grain_name": old.grain_name}
            if not ({None, "child_slots"} & changed_fields[local_id]):
                call_slots = {
                    call.slot_name
                    for call in workflow.repeatable_calls
                    if call.caller_local_id == local_id
                }
                updates["child_slot_names"] = tuple(
                    slot for slot in old.child_slot_names if slot not in call_slots
                )
            new = replace(new, **updates)
        nodes[local_id] = new
        unresolved.extend(
            BuildDeficit(
                code="design_choice_unresolved",
                field_path=item["field_path"],
                detail=item["detail"],
                episode_local_id=local_id,
            )
            for item in payload["unresolved"]
        )

    replaced_edges = {
        local_id
        for local_id, fields in changed_fields.items()
        if None in fields or "child_slots" in fields
    }
    edges = [
        edge for edge in current.edges if edge.parent_local_id not in replaced_edges
    ]
    for local_id in sorted(replaced_edges):
        for slot in payloads[local_id]["child_slots"]:
            child = nodes.get(slot["child_local_id"])
            if child is None or child.parent_local_id != local_id:
                raise ValueError(
                    "plan slots require an existing approved direct child's plan"
                )
            if slot["child_interface"] != child.interface or any(
                canonical_json(slot[key]) != canonical_json(getattr(child, key))
                for key in ("request_payload_contract", "result_payload_contract")
            ):
                raise ValueError(
                    "coordinated edge repair must match the exact child interface and payloads"
                )
            edges.append(materialize_edge_choices(local_id, child, slot))

    # Rebind only already-approved calls. Interface changes can affect another
    # caller; affected_paths below includes it for the common scope check.
    calls = []
    for call in workflow.repeatable_calls:
        if (
            call.caller_local_id not in nodes
            or call.callee_template_local_id not in nodes
        ):
            continue
        caller, edge = materialize_call(call, nodes, _library_functions())
        nodes[caller.local_id] = caller
        calls.append(edge)
    dispositions = dict(current.node_dispositions)
    for local_id in proposed:
        dispositions.setdefault(
            local_id, "full" if current.predecessor_plan_id is None else "directive"
        )
    # Keep incomplete work representable while the native checks derive its
    # actual deficits. The marker itself never becomes persisted evidence.
    plan = replace(
        current,
        nodes=tuple(nodes.values()),
        edges=tuple(edges),
        repeatable_calls=tuple(calls),
        node_dispositions=dispositions,
        deficits=(
            *(item for item in current.deficits if not (
                item.code == "design_choice_unresolved" and item.episode_local_id in proposed
            )),
            *unresolved,
            _CHECKING,
        ),
    )
    return _checked_plan(plan, inputs)


def affected_paths(before, after):
    def pieces(plan):
        return {
            node.module_name.replace(".", "/") + ".py": (
                node.as_record(),
                [
                    edge.as_record()
                    for edge in plan.all_edges
                    if edge.parent_local_id == node.local_id
                ],
            )
            for node in plan.nodes
        }

    old, new = pieces(before), pieces(after)
    return sorted(
        path for path in old.keys() | new.keys() if old.get(path) != new.get(path)
    )
