"""Shared repair-history comparison; no transcript summaries or retry budgets."""

from itertools import combinations

from agent.duet_contracts import canonical_json, digest_record

from .evaluation_inputs import semantic_inputs
from .records import Ref
from .state_machine import derived
from .coordination import ancestors


def _content(view, candidate, materialization=None):
    from .materialization_edits import stored_plan
    from .instrument_builds import entries

    def meaning(plan):
        return {
            key: plan.get(key)
            for key in (
                "workflow_hash",
                "root_local_id",
                "nodes",
                "edges",
                "repeatable_calls",
            )
        }

    content = {
        "files": candidate.body["files"],
        "materialization": meaning(stored_plan(view, candidate, materialization)),
    }
    instruments = entries(view)
    if instruments:
        content["instrument_plans"] = {
            item["spec_ref"]["artifact_id"]: meaning(
                stored_plan(view, candidate, materialization, instrument=item)
            )
            for item in instruments
        }
    return digest_record(content)


def owner(view, assignments, requirements):
    """Nearest common Parts owner, including calls not shaped like target nodes."""
    paths = [ancestors(view, assignment) for assignment in assignments]
    for candidate in paths[0]:
        if candidate.body["role"] != "parts" or not set(requirements).issubset(
            candidate.body["scope_requirement_keys"]
        ):
            continue
        if not all(any(item.ref == candidate.ref for item in path) for path in paths):
            continue
        matches = [
            entry.key
            for entry in view.entries("invocation")
            if entry.record.ref == candidate.ref
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def exact_revisit(view, attempt, candidate, materialization=None):
    previous = view.candidate
    prior_matches = []
    while True:
        if _content(view, previous) == _content(view, candidate, materialization):
            prior_matches.append(previous)
        parent = previous.body["parent_candidate_ref"]
        if parent is None:
            break
        previous = view.read(Ref.from_record(parent), "candidate")
    if not prior_matches:
        return []
    assignment = view.entry("invocation", attempt.body["invocation_id"]).record
    requirements = assignment.body["scope_requirement_keys"]
    return [
        derived(
            view,
            attempt,
            "conflict",
            {
                "requirement_keys": requirements,
                "observation_refs": [],
                "transition_refs": [item.ref.as_record() for item in prior_matches],
                "kind": "exact_revisit",
                "scope_owner_invocation_id": owner(view, [assignment], requirements),
                "involved_assignment_refs": [assignment.ref.as_record()],
                "applicability_ref": view.contract.body["environment_ref"],
                # A repeated source revision with new independent evidence is legitimate.
                "state": "suspected",
                "resolution_ref": None,
            },
        )
    ]


def conflicting_observation(view, attempt, current):
    """Conflicting evidence for one fixed criterion cannot be last-write-wins."""
    if current.body["outcome"] not in {"pass", "fail"}:
        return []
    request = view.read(Ref.from_record(current.body["request_ref"]), "evaluation")
    cohort_keys = (
        "candidate_ref",
        "measure_ref",
        "environment_ref",
        "input_refs",
        "harness_ref",
        "purpose",
    )
    cohort = canonical_json({
        **{key: request.body[key] for key in cohort_keys},
        "input_refs": semantic_inputs(view, request.body),
    })
    prior = []
    for entry in view.entries("observation"):
        item = entry.record
        if (
            item.body["check_key"] != current.body["check_key"]
            or item.body["outcome"] not in {"pass", "fail"}
            or item.body["outcome"] == current.body["outcome"]
        ):
            continue
        earlier = view.read(Ref.from_record(item.body["request_ref"]), "evaluation")
        if (
            canonical_json({
                **{key: earlier.body[key] for key in cohort_keys},
                "input_refs": semantic_inputs(view, earlier.body),
            })
            == cohort
        ):
            prior.append(item)
    if not prior:
        return []
    observations = [*prior, current]
    assignments = {
        view.entry("invocation", item.invocation_id.value).record.ref
        for item in observations
    }
    requirements = [
        view.entry("check", current.body["check_key"]).record.body["requirement_key"]
    ]
    return [
        derived(
            view,
            attempt,
            "conflict",
            {
                "requirement_keys": requirements,
                "observation_refs": [item.ref.as_record() for item in observations],
                "transition_refs": [request.body["candidate_ref"]],
                "kind": "dependency_conflict",
                "scope_owner_invocation_id": owner(
                    view,
                    [
                        view.read(ref, "assignment")
                        for ref in sorted(
                            assignments, key=lambda item: item.artifact_id.value
                        )
                    ],
                    requirements,
                ),
                "involved_assignment_refs": [
                    ref.as_record()
                    for ref in sorted(
                        assignments, key=lambda item: item.artifact_id.value
                    )
                ],
                "applicability_ref": request.body["environment_ref"],
                "state": "decision_required",
                "resolution_ref": None,
            },
            evidence=tuple(
                dict.fromkeys(
                    ref for item in observations for ref in item.evidence_refs
                )
            ),
        )
    ]


def opposing_regressions(view, attempt, current):
    current_request = view.read(
        Ref.from_record(current.body["request_ref"]), "evaluation"
    )
    if Ref.from_record(current_request.body["candidate_ref"]) != view.candidate.ref:
        return []  # a late result must not reorder the actual repair history
    revisions = []
    candidate = view.candidate
    while True:
        revisions.append(candidate)
        if candidate.body["parent_candidate_ref"] is None:
            break
        candidate = view.read(
            Ref.from_record(candidate.body["parent_candidate_ref"]), "candidate"
        )
    revision_order = {
        item.artifact_id.value: number
        for number, item in enumerate(reversed(revisions))
    }
    observations = [
        (entry.sequence, entry.record) for entry in view.entries("observation")
    ]
    observations.append((view.head["sequence"] + 1, current))
    groups = {}
    for sequence, observation in observations:
        if observation.body["outcome"] not in {"pass", "fail"}:
            continue
        request = view.read(
            Ref.from_record(observation.body["request_ref"]), "evaluation"
        )
        candidate_key = request.body["candidate_ref"]["artifact_id"]
        if candidate_key not in revision_order:
            continue
        # Explicit case bindings fix each check's inputs. Their vectors must be
        # compared together: fixing input A can break input B. Legacy checks
        # with no such binding still require the same shared instrument cohort.
        check = view.entry("check", observation.body["check_key"]).record
        cohort = canonical_json({
            **{
                key: request.body[key]
                for key in (
                    "environment_ref",
                    "measure_ref",
                    "purpose",
                )
            },
            **(
                {"check_bound_instruments": True}
                if "execution_binding" in check.body
                else {
                    "harness_ref": request.body["harness_ref"],
                    "input_refs": semantic_inputs(view, request.body),
                }
            ),
        })
        group = groups.setdefault(cohort, {})
        candidate = group.setdefault(
            candidate_key,
            {"sequence": revision_order[candidate_key], "checks": {}, "outcomes": {}},
        )
        candidate["outcomes"].setdefault(observation.body["check_key"], set()).add(
            observation.body["outcome"]
        )
        candidate["checks"][observation.body["check_key"]] = observation
    conflicts = []
    for candidates in groups.values():
        ordered = sorted(candidates.values(), key=lambda item: item["sequence"])
        current_key = current.body["check_key"]
        all_keys = set().union(*(set(item["checks"]) for item in ordered))
        for left, right in combinations(sorted(all_keys), 2):
            if current_key not in (left, right):
                continue
            complete = [
                item
                for item in ordered
                if left in item["checks"]
                and right in item["checks"]
                and all(len(item["outcomes"][key]) == 1 for key in (left, right))
            ]
            if len(complete) < 3:
                continue
            recent = complete[-3:]
            vectors = [
                tuple(item["checks"][key].body["outcome"] for key in (left, right))
                for item in recent
            ]
            if not (
                vectors[0] == vectors[2]
                and vectors[1] == vectors[0][::-1]
                and set(vectors[0]) == {"pass", "fail"}
            ):
                continue
            evidence = [item["checks"][key] for item in recent for key in (left, right)]
            if current.ref not in [item.ref for item in evidence]:
                continue
            assignments = {
                view.entry(
                    "invocation", item.invocation_id.value
                ).record.artifact_id.value: view.entry(
                    "invocation", item.invocation_id.value
                ).record
                for item in evidence
            }
            for item in evidence:
                request = view.read(
                    Ref.from_record(item.body["request_ref"]), "evaluation"
                )
                candidate = view.read(
                    Ref.from_record(request.body["candidate_ref"]), "candidate"
                )
                if candidate.body["change_set_ref"] is not None:
                    change = view.read(
                        Ref.from_record(candidate.body["change_set_ref"]), "change"
                    )
                    editor = view.read(
                        Ref.from_record(change.body["assignment_ref"]), "assignment"
                    )
                    assignments[editor.artifact_id.value] = editor
            assignments = dict(sorted(assignments.items()))
            requirements = sorted({
                view.entry("check", key).record.body["requirement_key"]
                for key in (left, right)
            })
            owning_id = owner(view, list(assignments.values()), requirements)
            active_assignment = view.entry(
                "invocation", attempt.body["invocation_id"]
            ).record
            needs_owner = len(assignments) > 1 or not set(requirements).issubset(
                active_assignment.body["scope_requirement_keys"]
            )
            signature = {
                "kind": "opposing_regression",
                "requirement_keys": requirements,
                "involved_assignment_refs": [
                    item.ref.as_record() for item in assignments.values()
                ],
            }
            if any(
                entry.status == "decision_required"
                and all(
                    canonical_json(entry.record.body[key]) == canonical_json(value)
                    for key, value in signature.items()
                )
                for entry in view.entries("conflict")
            ):
                continue
            conflicts.append(
                derived(
                    view,
                    attempt,
                    "conflict",
                    {
                        **signature,
                        "observation_refs": [item.ref.as_record() for item in evidence],
                        "transition_refs": [
                            view.read(Ref.from_record(item.body["request_ref"])).body[
                                "candidate_ref"
                            ]
                            for item in evidence
                        ],
                        "scope_owner_invocation_id": owning_id,
                        "applicability_ref": view.contract.body["environment_ref"],
                        "state": "decision_required" if needs_owner else "suspected",
                        "resolution_ref": None,
                    },
                    evidence=tuple(
                        dict.fromkeys(
                            ref for item in evidence for ref in item.evidence_refs
                        )
                    ),
                )
            )
    return conflicts
