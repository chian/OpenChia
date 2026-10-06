"""Registered dependency reads do not grant writes, networking or execution.

These are kernel-policy invariants, not workflow or model acceptance tests.
Each policy is installed only in its disposable child process.
"""

import json
import subprocess
import sys

import pytest

from agent.episode_contracts import OpaqueId
from episode_runtime.landlock import LandlockPolicyReceipt, landlock_abi7_policy_hash
from episode_runtime.seccomp import SeccompPolicyReceipt, seccomp_policy_hash


_PROBE = r'''
import ctypes, importlib, importlib.resources, json, os, socket, subprocess, sys, sysconfig
from pathlib import Path
from agent.episode_contracts import OpaqueId
from episode_runtime.landlock import apply_landlock_abi7, LandlockError
from episode_runtime.seccomp import apply_seccomp_policy

root, outside, dependency_reads = sys.argv[1], sys.argv[2], sys.argv[3] == "true"
sys.dont_write_bytecode = True
sys.path.insert(0, root)
assert "prepared_dependency" not in sys.modules
run, executor = OpaqueId("run_" + "a" * 32), OpaqueId("executor_" + "b" * 32)
stdlib = sysconfig.get_path("stdlib")
seccomp = apply_seccomp_policy(run_id=run, executor_instance_id=executor,
                               dependency_reads=dependency_reads)
try:
    landlock = apply_landlock_abi7(run_id=run, executor_instance_id=executor,
        read_only_paths=(root, stdlib) if dependency_reads else ())
except LandlockError as exc:
    if "kernel reported" in str(exc) or "Landlock ABI query failed" in str(exc):
        print(json.dumps({"unavailable": str(exc)}))
        sys.exit(0)
    raise

observed = {"seccomp": seccomp.as_record(), "landlock": landlock.as_record()}
try:
    dependency = importlib.import_module("prepared_dependency")
    observed["answer"] = dependency.answer()
except (PermissionError, ModuleNotFoundError):
    observed["answer"] = None

def read_outside():
    with open(outside, encoding="utf-8") as stream:
        return stream.read()

def write(flags):
    descriptor = os.open(root + "/prepared_dependency/data.txt", flags)
    os.close(descriptor)

def spawn():
    subprocess.run([sys.executable, "-c", "pass"], check=True)

operations = {
    "outside_read": read_outside,
    "write": lambda: write(os.O_WRONLY),
    "read_write": lambda: write(os.O_RDWR),
    "truncate": lambda: write(os.O_RDONLY | os.O_TRUNC),
    "create": lambda: write(os.O_RDONLY | os.O_CREAT),
    "network": lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM),
    "process": spawn,
}
for name, operation in operations.items():
    try:
        operation()
    except PermissionError:
        observed[name] = "denied"
    else:
        observed[name] = "allowed"
print(json.dumps(observed))
'''


@pytest.mark.platforms("linux")
@pytest.mark.parametrize("dependency_reads", [False, True])
def test_dependency_import_and_data_reads_preserve_effect_denials(tmp_path, dependency_reads):
    site = tmp_path / "prepared-site"
    package = site / "prepared_dependency"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from importlib.resources import files\n"
        "def answer():\n"
        "    return int(files(__package__).joinpath('data.txt').read_text(encoding='utf-8'))\n",
        encoding="utf-8",
    )
    data = package / "data.txt"
    data.write_text("42", encoding="utf-8")
    outside = tmp_path / "unregistered.txt"
    outside.write_text("not granted", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _PROBE, str(site), str(outside), str(dependency_reads).lower()],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout)
    if "unavailable" in observed:
        pytest.skip(observed["unavailable"])
    assert observed.pop("answer") == (42 if dependency_reads else None)
    landlock = LandlockPolicyReceipt.from_record(observed.pop("landlock"))
    seccomp = SeccompPolicyReceipt.from_record(observed.pop("seccomp"))
    assert landlock.dependency_reads == seccomp.dependency_reads == dependency_reads
    assert (str(site) in landlock.read_only_paths) == dependency_reads
    assert set(observed.values()) == {"denied"}, observed
    assert data.read_text(encoding="utf-8") == "42"
    assert outside.read_text(encoding="utf-8") == "not granted"


def test_dependency_receipts_bind_paths_and_cannot_claim_default_policy():
    run, executor = OpaqueId("run_" + "a" * 32), OpaqueId("executor_" + "b" * 32)
    paths = ("/prepared/site-packages", "/runtime/stdlib")
    receipt = LandlockPolicyReceipt(
        run, executor, policy_hash=landlock_abi7_policy_hash(dependency_reads=True),
        dependency_reads=True, read_only_paths=paths,
    )
    assert LandlockPolicyReceipt.from_record(receipt.as_record()) == receipt
    changed = {**receipt.as_record(), "read_only_paths": ["/another/site-packages", paths[1]]}
    with pytest.raises(ValueError, match="identity is stale"):
        LandlockPolicyReceipt.from_record(changed)
    with pytest.raises(ValueError, match="exact ABI 7 policy"):
        LandlockPolicyReceipt(run, executor, dependency_reads=True, read_only_paths=paths)
    with pytest.raises(ValueError, match="another policy"):
        SeccompPolicyReceipt(run, executor, "x86_64", seccomp_policy_hash("x86_64"), dependency_reads=True)
    default = LandlockPolicyReceipt(run, executor).as_record()
    assert default["policy"]["allow_rule_count"] == 0 and "read_only_paths" not in default
    assert LandlockPolicyReceipt.from_record(default).as_record() == default
