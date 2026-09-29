from __future__ import annotations

import json
from pathlib import Path

from agent.generic_creator_models import GenericCreatorInstanceSpec
from agent.generic_creator_templates import validate_template_spec


ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_wire_format_example_is_an_admissible_template_spec() -> None:
    record = _load(ROOT / "examples/generic_creators/plan_context_instance_v1.json")
    spec = GenericCreatorInstanceSpec.from_record(record)
    validate_template_spec(spec)
    assert spec.content_hash.value.startswith("sha256:")


def test_genome_example_keeps_domain_policy_in_task_spec_and_is_offline() -> None:
    record = _load(ROOT / "examples/generic_creators/genome_annotation_task_v1.json")
    assert record["production_submissions_permitted"] is False
    assert record["test_policy"]["perform_production_bv_brc_submission"] is False
    assert record["authentication"]["persist_raw_credentials"] is False
    assert record["cross_cutting_contracts"][0]["display_name"] == "REMOTE_DATA_PLANE"
    types = {item["creator_type"] for item in record["creator_instances"]}
    assert "worklist_factory_creator" in types
    assert "agent_loop_designer_creator" in types
    assert "integration_handoff_creator" in types
    assert "qualification_release_creator" in types


def test_published_json_schemas_are_well_formed_json() -> None:
    schemas = ROOT / "schemas/openchia"
    loaded = [_load(path) for path in sorted(schemas.glob("*.schema.json"))]
    assert len(loaded) == 3
    assert all(item["$schema"].endswith("2020-12/schema") for item in loaded)
