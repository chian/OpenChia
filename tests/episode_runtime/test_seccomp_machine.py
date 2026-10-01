"""The seccomp policy hash must not depend on the host's spelling of the architecture."""
from __future__ import annotations

import pytest

from episode_runtime import seccomp


@pytest.mark.parametrize("spelling", ["arm64", "ARM64", "aarch64", "AArch64"])
def test_apple_and_kernel_spellings_hash_the_same_policy(spelling):
    assert seccomp.normalize_machine(spelling) == "aarch64"
    assert seccomp.seccomp_policy_hash(spelling) == seccomp.seccomp_policy_hash("aarch64")
    assert seccomp.seccomp_policy_record(spelling)["machine"] == "aarch64"


def test_amd64_is_x86_64():
    assert seccomp.seccomp_policy_hash("amd64") == seccomp.seccomp_policy_hash("x86_64")


def test_host_policy_matches_a_container_on_the_same_cpu(monkeypatch):
    monkeypatch.setattr(seccomp.platform, "machine", lambda: "arm64")
    host = seccomp.seccomp_policy_hash()
    monkeypatch.setattr(seccomp.platform, "machine", lambda: "aarch64")
    container = seccomp.seccomp_policy_hash()
    assert host == container
