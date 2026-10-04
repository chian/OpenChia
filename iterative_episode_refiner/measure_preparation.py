"""Make registered task evidence available to the existing Measure Episode.

The approved build policy selects exact sources. Sources see only the original
requirements and workflow, never candidate output. The parent still chooses the
requirements, instrument and experiments; these records neither install checks
nor change the original acceptance requirements.
"""

from function_library.epistemic_contract import exact
from function_library.refinement_grounding import (
    refinement_grounding_library,
    resolve_grounding,
)

from .measure_needs import admission_policy
from .records import Ref


def build_measure_policy(data):
    sources = []
    for function in refinement_grounding_library.functions():
        selection = function.bind("entry").as_record()
        selection.pop("name")
        sources.append(data("grounding_function", selection).as_record())
    return {
        "adequacy_measure_ref": data(
            "measure_adequacy",
            {
                "criterion": "Retain the original requirement and distinguish independently grounded satisfactory and violating controls.",
            },
        ).as_record(),
        "grounding_refs": [],
        "source_function_refs": sources,
    }


def prepare_grounding(
    *,
    data,
    read_data,
    policy,
    catalog,
    catalog_ref,
    workflow,
    workflow_ref,
    environment_ref,
):
    grant = admission_policy(policy)
    if grant is None or not grant.get("source_function_refs"):
        return policy
    cases = list(grant["grounding_refs"])
    for raw in grant["source_function_refs"]:
        source = Ref.from_record(raw)
        selection = read_data(source)
        derive = resolve_grounding(selection)
        for requirement in catalog["requirements"]:
            recipe = derive(workflow=workflow, requirement=requirement)
            if recipe is None:
                continue
            exact(
                recipe,
                {
                    "predicate",
                    "expected",
                    "observation_path",
                    "positive_controls",
                    "negative_controls",
                    "input_domain",
                    "observation_schema",
                    "independence",
                    "limitations",
                },
                "registered requirement grounding",
            )
            origin = data(
                "requirement_grounding",
                {
                    "source_function_ref": raw,
                    "requirement_catalog_ref": catalog_ref.as_record(),
                    "target_workflow_ref": workflow_ref.as_record(),
                    "requirement_key": requirement["requirement_key"],
                    "derivation": recipe,
                },
            )
            shared = {
                "requirement_key": requirement["requirement_key"],
                "expected": recipe["expected"],
                "observation_path": recipe["observation_path"],
                "dependency_paths": None,
                "environment_ref": environment_ref.as_record(),
                "oracle_ref": origin.as_record(),
                "input_domain_ref": data(
                    "measure_domain", recipe["input_domain"]
                ).as_record(),
                "observation_schema_ref": data(
                    "measure_schema", recipe["observation_schema"]
                ).as_record(),
                "decision_function_ref": data(
                    "predicate", recipe["predicate"]
                ).as_record(),
                "independence_policy_ref": data(
                    "measure_independence", {"basis": recipe["independence"]}
                ).as_record(),
                "uncertainty_policy_ref": data(
                    "measure_uncertainty", {"limitations": recipe["limitations"]}
                ).as_record(),
                "limitation_refs": [
                    data("measure_limitation", {"text": text}).as_record()
                    for text in recipe["limitations"]
                ],
                "guard_keys": [],
            }
            for field, polarity in (("positive", "pass"), ("negative", "fail")):
                shared[f"{field}_control_refs"] = [
                    data(
                        "grounding_control",
                        {"observed": value, "expected_outcome": polarity},
                    ).as_record()
                    for value in recipe[f"{field}_controls"]
                ]
            for binding in policy["evaluation_bindings"]:
                if binding["purpose"] not in {"local", "acceptance", "composition"}:
                    continue
                harness = read_data(Ref.from_record(binding["harness_ref"]))
                if (
                    harness.get("execution_kind") != "target_workflow"
                    or harness.get("target_workflow_ref") != workflow_ref.as_record()
                    or binding["input_refs"]
                ):
                    continue
                case = data(
                    "grounded_case",
                    {
                        **shared,
                        "purpose": binding["purpose"],
                        "execution_binding": {
                            key: binding[key]
                            for key in (
                                "harness_ref",
                                "capability_ref",
                                "input_refs",
                            )
                        },
                    },
                )
                if case.as_record() not in cases:
                    cases.append(case.as_record())
    return {**policy, "measure_admission": {**grant, "grounding_refs": cases}}
