"""Mirror cgroup-v2 limits without confusing the real and namespace roots.

Fixtures use real file reads, not a mocked parser or a launched executor.
"""

from fractions import Fraction

import pytest

from episode_runtime.executor import ExecutorResources, RunExecutionError, _systemd_properties


def _controls(directory, *, quota, period, memory, pids, weight):
    directory.mkdir(parents=True, exist_ok=True)
    values = {
        "cpu.max": f"{quota} {period}",
        "memory.max": str(memory),
        "pids.max": str(pids),
        "cpu.weight": str(weight),
    }
    for name, value in values.items():
        (directory / name).write_text(value, encoding="ascii")
    return {
        "quota": quota, "period": period, "memory": memory,
        "pids": pids, "weight": weight,
    }


def _hierarchy(tmp_path, root_kind):
    root = tmp_path / "cgroup"
    parent, leaf = root / "user", root / "user" / "scope"
    allocations = [
        _controls(leaf, quota=90_000, period=100_000, memory=4096, pids=40, weight=73),
        _controls(parent, quota=150_000, period=200_000, memory=2048, pids=80, weight=91),
    ]
    for directory in (leaf, parent):
        (directory / "cgroup.type").write_text("domain", encoding="ascii")
    for directory in (root, parent, leaf):
        (directory / "cgroup.controllers").write_text("cpu memory pids", encoding="ascii")
        (directory / "cgroup.subtree_control").write_text(
            "" if directory == leaf else "cpu memory pids", encoding="ascii",
        )
    if root_kind != "true_root":
        allocations.append(
            _controls(root, quota=50_000, period=250_000, memory=1024, pids=20, weight=61)
        )
    if root_kind == "namespace_root":
        (root / "cgroup.type").write_text("domain", encoding="ascii")
    membership = tmp_path / "process.cgroup"
    membership.write_text("0::/user/scope\n", encoding="ascii")
    return root, parent, leaf, membership, allocations


def _disable_leaf(parent, leaf, controllers):
    remaining = " ".join(sorted({"cpu", "memory", "pids"} - set(controllers)))
    (leaf / "cgroup.controllers").write_text(remaining, encoding="ascii")
    (parent / "cgroup.subtree_control").write_text(remaining, encoding="ascii")
    for filename in ("cpu.max", "cpu.weight", "memory.max", "pids.max"):
        if filename.split(".", 1)[0] in controllers:
            (leaf / filename).unlink()


@pytest.mark.platforms("linux")
@pytest.mark.parametrize("root_kind", ("true_root", "namespace_root", "present_controls"))
@pytest.mark.parametrize("disabled", ((), ("cpu",), ("cpu", "memory", "pids")))
def test_allocation_keeps_visible_limits_and_only_omits_demonstrably_absent_controls(tmp_path, root_kind, disabled):
    root, parent, leaf, membership, allocations = _hierarchy(tmp_path, root_kind)
    _disable_leaf(parent, leaf, disabled)

    def discover():
        return ExecutorResources.from_host_effective_allocation(
            cgroup_root=root, process_cgroup_path=membership,
        )

    resources = discover()
    cpu_allocations = allocations[1:] if "cpu" in disabled else allocations
    tightest = min(cpu_allocations, key=lambda row: Fraction(row["quota"], row["period"]))
    assert resources.cpu_quota_per_sec_micros == Fraction(
        tightest["quota"] * 1_000_000, tightest["period"],
    )
    assert resources.cpu_period_micros == tightest["period"]
    assert resources.memory_max_bytes == min(
        row["memory"] for row in (allocations[1:] if "memory" in disabled else allocations)
    )
    assert resources.pids_max == min(
        row["pids"] for row in (allocations[1:] if "pids" in disabled else allocations)
    )
    assert resources.cpu_weight == cpu_allocations[0]["weight"]
    properties = dict(item.split("=", 1) for item in _systemd_properties(resources, ()))
    assert properties["CPUQuota"].endswith("%")
    assert Fraction(properties["CPUQuota"][:-1]) / 100 == Fraction(
        resources.cpu_quota_per_sec_micros, 1_000_000,
    )

    directories = [leaf, parent] + ([root] if root_kind != "true_root" else [])
    for directory, original in zip(directories, allocations):
        for filename in ("cpu.max", "memory.max", "pids.max"):
            control = directory / filename
            if control.exists():
                control.write_text(
                    f"max {original['period']}" if filename == "cpu.max" else "max",
                    encoding="ascii",
                )
    unlimited = discover()
    assert unlimited.cpu_quota_per_sec_micros is None
    assert unlimited.memory_max_bytes is None and unlimited.pids_max is None
    assert unlimited.cpu_period_micros == cpu_allocations[0]["period"]
    assert unlimited.cpu_weight == resources.cpu_weight
    unlimited_properties = dict(
        item.split("=", 1) for item in _systemd_properties(unlimited, ())
    )
    assert unlimited_properties["CPUQuota"] == ""
    assert unlimited_properties["MemoryMax"] == unlimited_properties["TasksMax"] == "infinity"

    membership.write_text("0::/\n", encoding="ascii")
    if root_kind == "true_root":
        with pytest.raises(RunExecutionError, match="no visible CPU-controlled ancestor"):
            discover()
    else:
        root_resident = discover()
        assert root_resident.cpu_period_micros == allocations[-1]["period"]
        assert root_resident.cpu_weight == allocations[-1]["weight"]


@pytest.mark.platforms("linux")
@pytest.mark.parametrize(
    "filename,location,fault",
    [
        *(
            (filename, location, fault)
            for filename in ("cpu.max", "cpu.weight", "memory.max", "pids.max")
            for location, fault in (
                ("parent", "missing"), ("namespace_root", "missing"),
                *(
                    (location, fault)
                    for location in ("parent", "namespace_root", "present_controls")
                    for fault in ("malformed", "symlink", "directory")
                ),
            )
        ),
        *(('cpu.max', 'disabled_leaf', fault) for fault in (
            "missing_metadata", "malformed_metadata", "child_enabled", "parent_enabled",
        )),
    ],
)
def test_allocation_never_treats_unreadable_or_invalid_limits_as_unbounded(tmp_path, filename, location, fault):
    root_kind = "present_controls" if location == "present_controls" else "namespace_root"
    root, parent, leaf, membership, _ = _hierarchy(tmp_path, root_kind)
    if location == "disabled_leaf":
        _disable_leaf(parent, leaf, ("cpu", "memory", "pids"))
        actions = {
            "missing_metadata": lambda: (parent / "cgroup.subtree_control").unlink(),
            "malformed_metadata": lambda: (leaf / "cgroup.controllers").write_text("invalid/controller", encoding="ascii"),
            "child_enabled": lambda: (leaf / "cgroup.controllers").write_text("cpu", encoding="ascii"),
            "parent_enabled": lambda: (parent / "cgroup.subtree_control").write_text("cpu", encoding="ascii"),
        }
        actions[fault]()
    else:
        directory = parent if location == "parent" else root
        target = directory / filename
        target.unlink()
        if fault == "malformed":
            target.write_text("invalid", encoding="ascii")
        elif fault == "symlink":
            target.symlink_to(directory / "cgroup.controllers")
        elif fault == "directory":
            target.mkdir()
    with pytest.raises(RunExecutionError):
        ExecutorResources.from_host_effective_allocation(
            cgroup_root=root, process_cgroup_path=membership,
        )
