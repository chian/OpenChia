"""Every approved directive in a refinement chain reaches later builds.

Regression: a build after three approved refinements carried only the newest
refinement's directives, so the planner re-asked the Duet two questions it had
already settled (collection_count body shape, http_status omission)."""

from __future__ import annotations

from types import SimpleNamespace

from episode_builder import planner


def _id(value: str) -> SimpleNamespace:
    return SimpleNamespace(value=value)


def _directive(did: str, text: str, local_id: str | None = "root") -> SimpleNamespace:
    target = SimpleNamespace(episode_local_id=local_id, as_record=lambda: {"episode_local_id": local_id})
    return SimpleNamespace(directive_id=_id(did), instruction=text, target=target)


def _request(rid: str, directives: list[SimpleNamespace], predecessor_rid: str | None, notes=()) -> SimpleNamespace:
    return SimpleNamespace(
        build_request_id=_id(rid),
        refinement_proposal=SimpleNamespace(implementation_directives=tuple(directives)),
        refinement_decision=SimpleNamespace(implementation_directive_ids=tuple(d.directive_id for d in directives)),
        refinement_notes=tuple(notes),
        predecessor_receipt=None if predecessor_rid is None else SimpleNamespace(build_request_id=_id(predecessor_rid)),
    )


FIRST = _request("req-1", [_directive("d1", "collections array"), _directive("d2", "omit http_status")], None)
SECOND = _request("req-2", [_directive("d3", "credential mapping")], "req-1")
THIRD = _request("req-3", [_directive("d4", "method/path tokens"), _directive("d3", "credential mapping")], "req-2")
STORE = SimpleNamespace(read_build_request=lambda rid: {"req-1": FIRST, "req-2": SECOND}[rid.value])


def test_chain_is_walked_oldest_first() -> None:
    chain = planner.inherited_refinement_requests(THIRD, STORE)
    assert [r.build_request_id.value for r in chain] == ["req-1", "req-2"]
    assert planner.inherited_refinement_requests(FIRST, STORE) == ()


def test_all_approved_directives_are_projected_once_with_provenance() -> None:
    evidence = planner.approved_refinement_evidence_for_episode(
        THIRD, "root", inherited=planner.inherited_refinement_requests(THIRD, STORE))
    directives = evidence["approved_directives"]
    assert [d["directive_id"] for d in directives] == ["d1", "d2", "d3", "d4"]
    assert [d.get("inherited_from") for d in directives] == ["req-1", "req-1", "req-2", None]


def test_without_inherited_requests_behaviour_is_unchanged() -> None:
    evidence = planner.approved_refinement_evidence_for_episode(THIRD, "root")
    assert [d["directive_id"] for d in evidence["approved_directives"]] == ["d4", "d3"]
    assert planner.approved_refinement_evidence_for_episode(_request("req-0", [], None), "root") is None
