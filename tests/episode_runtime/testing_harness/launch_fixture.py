"""Actual human launch approval on fixture-owned durable stores."""

from threading import RLock
from types import SimpleNamespace

from agent.episode_contracts import OpaqueId
from agent.episode_launch_host import EpisodeLaunchHostMixin


class FixtureLaunchHost(EpisodeLaunchHostMixin):
    def __init__(self, artifacts, builds, duet_id):
        self.store, self.build_store = artifacts, builds
        self.identity = SimpleNamespace(duet_id=OpaqueId(duet_id))
        self._launch_lock = RLock()

    def approve_fixture(self, launch):
        self._launch_event("launch_configuration_selected", {
            "mode": "reuse", "selection_id": launch.configuration_hash,
            "spec": launch.record["requested_spec"],
        }, human=True)
        return self.approve_launch(launch.configuration_hash)
