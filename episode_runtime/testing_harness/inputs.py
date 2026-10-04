"""The same closed root launch envelope for experiments and refiner checks."""

from collections.abc import Mapping

from agent.duet_contracts import content_id
from function_library.epistemic_contract import exact
from handoff_library import DuetLaunchRequest


def workflow_template(workflow, template=None):
    roots = [
        node
        for node in workflow.workflow.episodes
        if node.workflow_parent_local_id is None
    ]
    if len(roots) != 1:
        raise ValueError("native validation requires one approved target root")
    expected = {
        "workflow_id": workflow.artifact_id.value,
        "goal_id": content_id(
            "goal", {"root_contract": roots[0].contract.as_record()}
        ).value,
    }
    if template is None:
        template = {
            **expected,
            "request_id": content_id("launch_request", expected).value,
            "artifact_ids_by_role": {},
            "measurements": {},
            "states": {},
            "flags": {},
        }
    exact(
        template,
        {
            "request_id",
            "workflow_id",
            "goal_id",
            "artifact_ids_by_role",
            "measurements",
            "states",
            "flags",
        },
        "validation launch input",
    )
    artifacts = template["artifact_ids_by_role"]
    if not isinstance(artifacts, Mapping) or any(
        not isinstance(ids, (list, tuple)) for ids in artifacts.values()
    ):
        raise ValueError("validation launch artifact roles require arrays of IDs")
    request = DuetLaunchRequest(
        request_id=template["request_id"],
        workflow_id=template["workflow_id"],
        goal_id=template["goal_id"],
        artifact_ids_by_role={role: tuple(ids) for role, ids in artifacts.items()},
        measurements=template["measurements"],
        states=template["states"],
        flags=template["flags"],
    )
    if (
        request.workflow_id != expected["workflow_id"]
        or request.goal_id != expected["goal_id"]
    ):
        raise ValueError("validation launch input names a different workflow or goal")
    return request
