"""The emitter must show the authoring model the exact import surface that
admission later enforces, so a build cannot be blocked for guessing a package
root (regression for ``agent.``-prefixed imports and a non-literal
``FunctionImplementation.module``)."""

from __future__ import annotations

import ast

from episode_builder import admission, emitter
from episode_builder.planner import materializer_function_catalog


def _record(entry: object) -> dict:
    return entry if isinstance(entry, dict) else entry.as_record()  # type: ignore[union-attr]


def test_module_contract_lists_every_admitted_import_root() -> None:
    surface = emitter._MODULE_CONTRACT["import_surface"]
    assert surface["admitted_import_roots"] == sorted(admission.ADMITTED_IMPORT_ROOTS)
    assert surface["library_packages"] == sorted(admission.INTERNAL_IMPLEMENTATION_ROOTS)
    assert set(surface["library_packages"]) <= set(surface["admitted_import_roots"])
    assert "agent" not in surface["admitted_import_roots"]
    assert "'agent.'" in surface["rule"]


def test_generated_implementation_shape_names_the_module_keyword() -> None:
    text = emitter._MODULE_CONTRACT["builder_runtime"]["generated_implementation"]
    assert 'FunctionImplementation(module="<target_module_name>"' in text
    assert "is_async" in text
    assert "uses target_module_name as" not in text
    assert "import_surface.admitted_import_roots" in emitter._EMITTER_SYSTEM_PROMPT


def test_catalog_definitions_only_name_admitted_package_roots() -> None:
    roots = admission.ADMITTED_IMPORT_ROOTS
    for entry in materializer_function_catalog():
        record = _record(entry)
        implementation = record.get("implementation")
        if implementation is not None:  # source-only reference entries carry none
            module = implementation["module"]
            assert module.split(".", 1)[0] in roots, module
        for field in ("input_type", "output_type"):
            value = record.get(field) or ""
            # Dotted type paths shown to the model must not advertise a package
            # root the module may not import.
            if "." in value and " " not in value:
                assert not value.startswith("agent."), (record["function_id"], value)


def test_admission_rejects_agent_prefixed_imports_the_contract_forbids() -> None:
    forbidden = emitter._imported_modules(
        ast.parse("from agent.method_loop import Episode\nimport agent.http_call_library\n")
    )
    for module in forbidden:
        assert module.split(".", 1)[0] not in admission.ADMITTED_IMPORT_ROOTS
