"""Candidate-specific projections of the shared Target Workflow environment service.

Recipes remain ordinary candidate blobs. Resolutions and preparation diagnostics
are host evidence, never coding-session state or a second execution journal.
"""

from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH, TargetEnvironmentRecipe
from function_library.models import _thaw_json

from .records import Ref


def saved_preparation(reader, contract, candidate, scope):
    rows = reader.duets.artifacts_by_kind(
        duet_id=contract.body["duet_id"], kind="refinement.environment_preparation.v1",
    )
    matches = [row for row in rows if (
        row["record"]["candidate_ref"] == candidate.ref.as_record()
        and row["record"]["source_workflow_ref"] == _thaw_json(scope.workflow_ref)
    )]
    if not matches:
        return None
    row = matches[-1]
    reference = Ref.from_record({key: row[key] for key in ("artifact_id", "content_hash")})
    return {**reader.reference(reference, contract.body["duet_id"]),
            "record_ref": reference.as_record()}


def validate_manifest(reader, contract, candidate, projection, inputs):
    """An admitted source cannot silently substitute another recipe or lock."""
    if inputs.manifest is None:
        return
    manifest = inputs.manifest.as_record()
    if manifest["environment_recipe"] != projection.environment_recipe:
        raise ValueError("admitted build changes the candidate environment recipe")
    if projection.scope.fixed:
        if manifest["environment_lock"] != projection.environment_lock:
            raise ValueError("admitted reference build changes its environment lock")
        return
    if projection.environment_recipe is None:
        return
    for row in reader.duets.artifacts_by_kind(
        duet_id=contract.body["duet_id"], kind="refinement.environment_preparation.v1",
    ):
        value = reader.reference(
            Ref.from_record({key: row[key] for key in ("artifact_id", "content_hash")}),
            contract.body["duet_id"],
        )
        if (value["candidate_ref"] == candidate.ref.as_record()
                and value["source_workflow_ref"] == _thaw_json(projection.scope.workflow_ref)
                and value["recipe"] == projection.environment_recipe
                and value["result"]["status"] == "prepared"
                and value["result"]["resolved_lock"] == manifest["environment_lock"]):
            return
    raise ValueError("admitted build lacks the exact candidate's successful environment resolution")


async def prepare_environment(evaluations, session, call, payload):
    from .candidate_source import project_candidate_sources
    candidate, plans = evaluations._plans(session, call, payload)
    projections = {}
    for plan in plans:
        if not plan["availability"]["executable"]:
            continue
        projection = project_candidate_sources(
            session.store.evidence, session.contract, candidate, plan["binding"],
        )
        key = projection.scope.workflow_ref["artifact_id"]
        projections[key] = projection
    for projection in projections.values():
        await prepare_candidate(evaluations, session, call, candidate, projection)


async def prepare_candidate(evaluations, session, call, candidate, projection):
    """One shared adapter for pre-edit diagnostics and post-edit validation."""
    invalid = [item.as_record() for item in projection.deficits
               if item.code == "environment_recipe_invalid"]
    recipe = projection.environment_recipe
    if recipe is None and not invalid:
        return None
    # Saved admission evidence is not a physical cache check. Even a resumed
    # unit must ask the shared service to verify its diagnostic environment.
    if invalid:
        path = projection.scope.paths[ENVIRONMENT_RECIPE_PATH]
        result = {"status": "failed", "prepared": None, "resolved_lock": None,
                  "diagnostics": invalid,
                  "log_refs": [{"store": "build_blob", "content_hash": candidate.body["files"][path]}],
                  "preparation_ref": None,
                  "python_executable": None, "site_packages": None}
    else:
        baseline = projection.baseline.manifest
        lock = None if baseline is None else baseline.as_record()["environment_lock"]
        if lock is not None and lock["recipe_hash"] != TargetEnvironmentRecipe.from_record(recipe).recipe_hash.value:
            lock = None
        result = await evaluations.environment_service(session).prepare(
            recipe, duet_id=session.duet_id, candidate_ref=candidate.ref.as_record(),
            resolved_lock=lock,
        )
    with session.view() as view:
        if view.candidate.ref != candidate.ref:
            raise ValueError("candidate changed during environment preparation")
    record = {
        "candidate_ref": candidate.ref.as_record(),
        "source_workflow_ref": _thaw_json(projection.scope.workflow_ref),
        "recipe_path": projection.scope.paths.get(ENVIRONMENT_RECIPE_PATH, ENVIRONMENT_RECIPE_PATH),
        "invocation_id": call.invocation_id.value,
        "unit_id": call.unit_id.value,
        "recipe": recipe,
        "result": result,
    }
    reference = session.put_data("environment_preparation", record)
    if result["status"] != "prepared":
        call.feedback_ref = reference
    return {**record, "record_ref": reference.as_record()}


def _outcome_finding(outcome):
    prepared = outcome["prepared"]
    return {
        "status": outcome["status"], "diagnostics": outcome["diagnostics"],
        "resolved_distributions": [] if prepared is None else prepared["distributions"],
        "log_refs": outcome["log_refs"], "preparation_ref": outcome.get("preparation_ref"),
        "meaning": "Environment preparation only; workflow correctness remains unmeasured.",
    }


def project_finding(value, reference):
    return {
        "recipe_path": value["recipe_path"],
        "candidate_ref": value["candidate_ref"],
        "source_workflow_ref": value["source_workflow_ref"],
        **_outcome_finding(value["result"]),
        "record_ref": reference.as_record(),
    }


def experiment_findings(result):
    """Keep target and checker setup failures when consuming shared Run results."""
    target = result.get("environment_preparation")
    if target is None:
        target = result.get("plan", {}).get("environment_preparation")
    outcomes = [] if target is None else [(result.get("environment_subject", "target_workflow"), target)]
    outcomes.extend(("measurement", row["environment_preparation"])
                    for row in result.get("instrument_runs", ())
                    if row.get("environment_preparation") is not None)
    return [{"subject": subject, **_outcome_finding(outcome)}
            for subject, outcome in outcomes]


def findings(view, *, invocation_id=None, candidate_ref=None):
    """Typed findings retain full-log references without copying command streams."""
    rows = view.connection.execute(
        "SELECT artifact_id, content_hash, kind FROM artifacts WHERE duet_id = ? "
        "AND kind IN ('refinement.environment_preparation.v1', "
        "'refinement.experiment_result.v1') ORDER BY rowid",
        (view.head["duet_id"],),
    )
    result = []
    for row in rows:
        reference = Ref.from_record({key: row[key] for key in ("artifact_id", "content_hash")})
        value = view.data(reference)
        if invocation_id is not None and value["invocation_id"] != invocation_id:
            continue
        if candidate_ref is not None and value["candidate_ref"] != candidate_ref:
            continue
        if row["kind"] == "refinement.environment_preparation.v1":
            result.append(project_finding(value, reference))
        else:
            result.extend({**item, "record_ref": reference.as_record()}
                          for item in value["environment_findings"])
    return result
