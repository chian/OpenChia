"""Typed experimental judgments, kept separate from parent acceptance and credit."""

from agent.duet_contracts import digest_record
from iterative_episode_refiner.records import project

from .judgments import judge_value
from .criteria import verify_implementation
from ..records.experiments import put_record, read_record
from ..records.outcomes import RequirementOutcome


def measurement_run(artifacts, experiment_id, *, runs=None):
    """Select a physical attempt through the shared immutable continuation links."""
    from ..contracts import RunRegistration
    from ..records.experiments import execution_attempts

    dispatch = read_record(artifacts, "dispatch", experiment_id=experiment_id)
    if dispatch is None:
        return None
    original = RunRegistration.from_record(dispatch["record"]["registration"])
    attempts = execution_attempts(artifacts, runs, original.run_id.value)
    return original if not attempts else RunRegistration.from_record(attempts[-1]["record"]["registration"])


def _measurement_sources(artifacts, experiment_id, *, runs=None):
    """Pin all physical evidence sources once, before any predicates execute."""
    from ..contracts import RunRegistration
    from ..records.experiments import execution_attempts

    dispatch = read_record(artifacts, "dispatch", experiment_id=experiment_id)
    target = measurement_run(artifacts, experiment_id, runs=runs)
    instruments = {}
    if dispatch is not None:
        for row in dispatch["record"]["plan"]["measurements"]:
            instrument = row.get("instrument")
            if instrument is None:
                continue
            key = instrument["instrument_id"]
            saved = read_record(artifacts, "instrument", experiment_id=experiment_id, instrument_id=key)
            if saved is None:
                continue
            bound = RunRegistration.from_record(saved["record"]["registration"])
            attempts = execution_attempts(artifacts, runs, bound.run_id.value)
            if attempts:
                bound = RunRegistration.from_record(attempts[-1]["record"]["registration"])
            instruments[key] = bound
    return target, instruments


def _measurement_identity(experiment_id, target, instruments):
    continued = any(
        registration is not None and registration.resume_from is not None
        for registration in (target, *instruments.values())
    )
    if not continued:
        return "measurement", {"experiment_id": experiment_id}
    executions = {
        "target_run_id": None if target is None else target.run_id.value,
        "instrument_run_ids": {key: value.run_id.value for key, value in instruments.items()},
    }
    return "measurement_attempt", {"experiment_id": experiment_id, "execution_set_hash": digest_record(executions).value}


def saved_measurements(artifacts, experiment_id):
    kind, identity = _measurement_identity(experiment_id, *_measurement_sources(artifacts, experiment_id))
    return _read_measurement(artifacts, experiment_id, kind, identity)


def _read_measurement(artifacts, experiment_id, kind, identity):
    row = read_record(artifacts, kind, **identity)
    if row is None:
        return None
    value = row["record"]
    if value["experiment_id"] != experiment_id:
        raise ValueError("measurement report names a different experiment")
    for outcome in value["outcomes"]:
        RequirementOutcome.model_validate(outcome)
    return {
        **value,
        "measurement_ref": {
            "artifact_id": row["artifact_id"],
            "content_hash": row["content_hash"],
        },
    }


def measure_execution(artifacts, runs, experiment_id):
    registration, instruments = _measurement_sources(artifacts, experiment_id, runs=runs)
    kind, identity = _measurement_identity(experiment_id, registration, instruments)
    prior = _read_measurement(artifacts, experiment_id, kind, identity)
    if prior is not None:
        return prior
    from .contracts import ExperimentSpec

    row = read_record(artifacts, "dispatch", experiment_id=experiment_id)
    if row is None:
        raise ValueError("measurement requires an exact committed experiment dispatch")
    binding = row["record"]
    request = ExperimentSpec.from_record(binding["spec"])
    if request.experiment_id != experiment_id:
        raise ValueError("measurement dispatch has a different experiment identity")
    run_id = registration.run_id
    evidence = runs.read_evidence(run_id)
    if runs.read_registration(run_id) != registration:
        raise ValueError("measurement evidence belongs to a different registered Run")
    evidence_ref = {
        "artifact_id": evidence.evidence_id.value,
        "content_hash": evidence.content_hash.value,
    }
    outcomes = []
    implementation_errors = {}
    if any(
        row.get("eligible") and row.get("implementation_ref") is None
        for row in binding["plan"]["measurements"]
    ):
        from .implementation import measurement_implementation

        actual = digest_record(measurement_implementation()).value
        implementation_errors[None] = (
            None
            if binding["plan"].get("measurement_implementation_hash") == actual
            else "Measurement implementation differs from the frozen experiment plan."
        )
    for resolved in binding["plan"]["measurements"]:
        if resolved.get("eligible"):
            reference = resolved["implementation_ref"]
            if reference is None:
                continue
            if reference["artifact_id"] not in implementation_errors:
                try:
                    verify_implementation(artifacts, reference, resolved.get("owner_duet_id", row["duet_id"]))
                except (OSError, RuntimeError, ValueError) as exc:
                    implementation_errors[reference["artifact_id"]] = str(exc)
                else:
                    implementation_errors[reference["artifact_id"]] = None
    for requirement, resolved in zip(
        binding["spec"]["requirements"], binding["plan"]["measurements"], strict=True
    ):
        criterion = resolved.get("criterion")
        measured_evidence = evidence
        checking_gap = None
        if (
            resolved.get("eligible")
            and resolved.get("instrument") is not None
            and evidence.terminal_status.value == "succeeded"
        ):
            instrument_id = resolved["instrument"]["instrument_id"]
            checker_registration = instruments.get(instrument_id)
            continued = checker_registration is not None and checker_registration.resume_from is not None
            instrument_result = read_record(
                artifacts,
                "instrument_result_attempt" if continued else "instrument_result",
                experiment_id=experiment_id,
                instrument_id=instrument_id,
                **({"run_id": checker_registration.run_id.value} if continued else {}),
            )
            checking_gap = (
                None
                if instrument_result is None
                else instrument_result["record"].get("checking_gap")
            )
            if checker_registration is None and checking_gap is None:
                raise ValueError(
                    "independent checker evidence is not available; target output cannot substitute"
                )
            if checker_registration is not None:
                checker_run = checker_registration.run_id
                measured_evidence = runs.read_evidence(checker_run)
                if (
                    runs.read_registration(checker_run)
                    != checker_registration
                ):
                    raise ValueError(
                        "independent checker evidence names another registration"
                    )
        observed, reason, status = None, None, "unavailable"
        if criterion is None:
            reason = resolved["reason"]
        elif not resolved["eligible"]:
            status, reason = "not_applicable", ", ".join(resolved["reasons"])
        elif checking_gap is not None:
            reason = f"Independent checker unavailable: {checking_gap['kind']}: {checking_gap['detail']}"
        elif implementation_errors[
            None
            if resolved["implementation_ref"] is None
            else resolved["implementation_ref"]["artifact_id"]
        ]:
            status, reason = (
                "error",
                implementation_errors[
                    None
                    if resolved["implementation_ref"] is None
                    else resolved["implementation_ref"]["artifact_id"]
                ],
            )
        elif measured_evidence.terminal_status.value != "succeeded":
            status, reason = (
                "error",
                "Execution did not return successfully; its stop is not a failed behavioral criterion.",
            )
        else:
            try:
                observed = project(
                    measured_evidence.as_record()["typed_status"],
                    criterion["observation_path"],
                )
            except (ValueError, KeyError, TypeError, IndexError):
                status, reason = (
                    "inconclusive",
                    "The frozen result projection is absent or incompatible with the typed return.",
                )
            else:
                try:
                    status = judge_value(
                        criterion["predicate"],
                        observed=observed,
                        expected=criterion["expected_value"],
                    )
                    if "required_outcome" in criterion:
                        reason = f"Grounded control expected {criterion['required_outcome']}; checker predicate returned {status}."
                        status = "pass" if status == criterion["required_outcome"] else "fail"
                except (ValueError, TypeError) as exc:
                    status, reason = "error", f"Registered measurement failed: {exc}"
        outcome = RequirementOutcome(
            requirement_ref=requirement["requirement_ref"],
            requirement_key=None if criterion is None else criterion["requirement_key"],
            measure_ref=requirement["measure_ref"],
            predicted=requirement["expected"],
            falsifying=requirement["falsifying"],
            status=status,
            observed=observed,
            criterion_expected=None
            if criterion is None
            else {"predicate_expected": criterion["expected_value"], "required_outcome": criterion["required_outcome"]}
            if "required_outcome" in criterion
            else criterion["expected_value"],
            evidence_ref={
                "artifact_id": measured_evidence.evidence_id.value,
                "content_hash": measured_evidence.content_hash.value,
            },
            reason=reason,
            limitations=[] if criterion is None else criterion["limitations"],
        )
        outcomes.append(outcome.model_dump(mode="json"))
    statuses = {row["status"] for row in outcomes}
    verdict = (
        "fail"
        if "fail" in statuses
        else "pass"
        if statuses == {"pass"}
        else "unmeasured"
    )
    report = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "candidate_ref": binding["spec"]["candidate_ref"],
        "candidate": binding["plan"]["candidate"],
        "scope": binding["plan"]["scope"],
        "context": {
            "environment_ref": binding["spec"]["environment_ref"],
            "launch_ref": binding["spec"]["launch_ref"],
        },
        "mode": binding["spec"]["mode"],
        "candidate_verdict": verdict,
        "outcomes": outcomes,
        "execution_ref": evidence_ref,
        "acceptance": {
            "admitted": False,
            "reason": "Criterion outcomes do not replace independent parent acceptance.",
        },
        "progress": {
            "admitted": False,
            "reason": "Measurements are evidence for the owning Episode; only its registered host controller can admit new progress.",
        },
        "unresolved_questions": binding["spec"]["unresolved_questions"],
        "limitations": [
            "A criterion pass applies only to its frozen scope, inputs and mode; it does not establish untested behavior.",
            "Declared satisfactory/violating controls test the predicate, not the truth or completeness of operator-supplied grounding.",
        ],
    }
    put_record(
        artifacts,
        kind,
        **identity,
        duet_id=row["duet_id"],
        record=report,
    )
    # Another caller may already be continuing a checker. Return this report's
    # pinned sources, never relabel it with a later attempt's identity.
    return _read_measurement(artifacts, experiment_id, kind, identity)
