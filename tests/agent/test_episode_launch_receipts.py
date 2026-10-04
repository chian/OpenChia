"""Launch receipts distinguish frozen routing from current host provenance."""

from copy import deepcopy

from agent.episode_launch import resolve_launch
from agent.episode_launch_host import resolved_launch_record
from tests.openchia_cli.test_episode_launch_setup import launch_spec


def test_continued_launch_reuses_configuration_not_predecessor_environment(tmp_path, monkeypatch):
    from types import SimpleNamespace

    spec = launch_spec(tmp_path, "receipt-only")
    spec["routes"]["reasoning"]["auth"] = {"kind": "none"}
    launch = resolve_launch(spec)
    selection = {"mode": "reuse", "reused_launch_id": "original-selection"}
    original = resolved_launch_record(
        launch, selection=selection, launch_id="original", kind="build", subject_id="first",
    )
    saved = deepcopy(original)
    monkeypatch.setattr(
        "openchia_cli.version_info.get_version_info",
        lambda: SimpleNamespace(commit="successor-host", branch="continued", dirty=True),
    )
    # A predecessor record is also the continuation's routing selection. Its
    # provenance fields must not become this host's environment attestation.
    predecessor = {**original, "client_packages": {"obsolete": "old"}, "code_hashes": {"obsolete": "old"}}
    continued = resolved_launch_record(
        launch, selection=predecessor, launch_id="successor", kind="build", subject_id="second",
    )
    assert continued["configuration"] == saved["configuration"]
    assert continued["configuration_hash"] == saved["configuration_hash"]
    assert continued["code"] == {"commit": "successor-host", "branch": "continued", "dirty": True}
    assert continued["client_packages"] == original["client_packages"]
    assert continued["code_hashes"] == original["code_hashes"]
    assert original == saved
