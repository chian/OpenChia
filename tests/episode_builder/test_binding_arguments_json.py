"""EpisodeFunctionBinding.arguments must be JSON-shaped; a HandoffPayloadContract
object there raises at module import inside the Run (``admit_request
arguments.payload_contract must contain only JSON-shaped values``)."""

from __future__ import annotations

import ast

from episode_builder import admission, emitter

HEAD = "from method_loop import EpisodeFunctionBinding\nREQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract()\nEMPTY = {}\n"


def _deficits(body: str) -> tuple[str, ...]:
    return admission._binding_argument_deficits(ast.parse(HEAD + body))


def test_contract_object_argument_is_a_deficit() -> None:
    found = _deficits('B = EpisodeFunctionBinding(name="admit_request", library="l", function_id="f", interface="i", definition_id="d", arguments={"payload_contract": REQUEST_PAYLOAD_CONTRACT})\n')
    assert len(found) == 1 and ".as_record()" in found[0]


def test_json_record_and_literals_pass() -> None:
    assert _deficits('B = EpisodeFunctionBinding(name="n", library="l", function_id="f", interface="i", definition_id="d", arguments={"payload_contract": REQUEST_PAYLOAD_CONTRACT.as_record()})\n') == ()
    assert _deficits('B = EpisodeFunctionBinding(name="n", library="l", function_id="f", interface="i", definition_id="d", arguments={"uncertainty_alpha": 0.05, "names": ["a", "b"], "x": None})\n') == ()
    assert _deficits('B = EpisodeFunctionBinding(name="n", library="l", function_id="f", interface="i", definition_id="d", arguments=EMPTY)\n') == ()


def test_contract_tells_the_model() -> None:
    text = emitter._MODULE_CONTRACT["binding_construction"]["EpisodeFunctionBinding"]
    assert "REQUEST_PAYLOAD_CONTRACT.as_record()" in text
    assert "REQUEST_PAYLOAD_CONTRACT.as_record()" in emitter._MODULE_CONTRACT["binding_construction"]["example"]
