"""The original estimator is discoverable with its actual history contract."""

import ast

from episode_builder import admission, emitter
from episode_builder.planner import materializer_function_catalog
from numeric_control_library import (
    COMPOSE_PREFERENTIAL_CONTROLLER,
    JOINT_PREFERENTIAL_DISCOVERY,
    PAIRED_INCIDENCE,
)
from numeric_control_library.preferential_control import preferential_function_library


def test_catalog_resolves_the_evaluated_original_estimator_and_composition():
    catalog = {
        entry["definition_id"]: entry for entry in materializer_function_catalog()
    }
    for function in (JOINT_PREFERENTIAL_DISCOVERY, COMPOSE_PREFERENTIAL_CONTROLLER):
        assert catalog[function.definition_id] == function.as_record()
        assert callable(function.load())
    assert preferential_function_library.evaluation_report(
        JOINT_PREFERENTIAL_DISCOVERY.component_id
    ).passed
    assert JOINT_PREFERENTIAL_DISCOVERY.interface != PAIRED_INCIDENCE.interface
    estimator = JOINT_PREFERENTIAL_DISCOVERY.load()(
        scope_path=(("scope", "catalog"),), epoch="catalog"
    )
    assert estimator.snapshot().method_version == "preferential_incidence_estimator_v2"


def test_generated_code_gets_matching_records_and_keyword_only_signatures():
    for module in (
        "numeric_control_library",
        "numeric_control_library.preferential_control",
    ):
        valid = (
            f"from {module} import PreferentialIncidenceObservation, PreferentialChannelSchema, "
            "PreferentialControllerConfig, compose_preferential_controller, joint_preferential_discovery\n"
            "value = PreferentialIncidenceObservation(('evidence:one',))\n"
            "schema = PreferentialChannelSchema(('overall',))\n"
            "control = PreferentialControllerConfig(('overall',), 0.01, {'overall': 0}, 1)\n"
            "factory = compose_preferential_controller(epoch='task', channel_schema=schema, control=control)\n"
            "estimator = joint_preferential_discovery(scope_path=(('scope', 'one'),), epoch='task')\n"
        )
        assert not admission._constructor_argument_deficits(ast.parse(valid))
        invalid = (
            valid + "bad = compose_preferential_controller('task', schema, control)\n"
        )
        assert any(
            "keyword-only" in item
            for item in admission._constructor_argument_deficits(ast.parse(invalid))
        )
        signatures = admission.constructor_signatures()
        assert (
            emitter._MODULE_CONTRACT["constructor_signatures"]["classes"][
                f"{module}.compose_preferential_controller"
            ]
            == signatures[f"{module}.compose_preferential_controller"]
        )
    assert (
        "JOINT_PREFERENTIAL_DISCOVERY"
        in emitter._library_exports()["numeric_control_library"]
    )
