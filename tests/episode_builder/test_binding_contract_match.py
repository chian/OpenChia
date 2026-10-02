"""Admission compares BINDING's frozen-contract fields byte for byte, the way
the runtime linker does, so a paraphrased `stopping` blocks the build instead
of killing the Run with ``RuntimeLinkError: BINDING changes the frozen node
contract``."""

from __future__ import annotations

import ast

from episode_builder import admission

EXPECTED = {
    "grain_name": "probe",
    "interface": "asm_next.probe",
    "topology_role": "leaf",
    "goal": "Confirm the tenant is reachable.",
    "unit": "One GET request.",
    "result": "Status codes and byte counts.",
    "progress": "Resolved probes over two.",
    "stopping": "After the two units, over observed probe outcomes.",
}

MODULE = '''
from method_loop import EpisodeBindingDeclaration, EpisodeTopologyRole
EPISODE_INTERFACE = "asm_next.probe"
STOPPING = {stopping!r}
BINDING = EpisodeBindingDeclaration(
    grain_name="probe", interface=EPISODE_INTERFACE, topology_role=EpisodeTopologyRole.LEAF,
    goal="Confirm the tenant is reachable.", unit="One GET request.",
    result="Status codes and byte counts.", progress="Resolved probes over two.",
    stopping={stopping_expr},
)
'''


def _check(stopping: str, stopping_expr: str = "STOPPING") -> list[str]:
    source = MODULE.format(stopping=stopping, stopping_expr=stopping_expr)
    return list(admission._binding_contract_deficits(ast.parse(source), EXPECTED))


def test_exact_copy_passes_through_literals_constants_and_enum() -> None:
    assert _check(EXPECTED["stopping"]) == []


def test_paraphrase_is_reported_with_the_first_differing_character() -> None:
    found = _check("After the two units, and observed probe outcomes.")
    assert len(found) == 1
    assert found[0].startswith("BINDING.stopping differs from the frozen contract at character 21")
    assert "copy the frozen text byte for byte" in found[0]


def test_role_mismatch_and_missing_field_are_reported() -> None:
    source = MODULE.format(stopping=EXPECTED["stopping"], stopping_expr="STOPPING").replace(
        "EpisodeTopologyRole.LEAF", "EpisodeTopologyRole.BRANCH"
    ).replace('unit="One GET request.",', "")
    found = list(admission._binding_contract_deficits(ast.parse(source), EXPECTED))
    assert "BINDING.topology_role is 'branch'; the frozen node requires 'leaf'" in found
    assert "BINDING omits unit" in found


def test_unresolvable_value_is_a_deficit_not_a_pass() -> None:
    found = _check(EXPECTED["stopping"], stopping_expr='f"{STOPPING}"')
    assert found == [
        "BINDING.stopping must be a string literal or a module-level constant so "
        "admission can compare it with the frozen contract"
    ]
