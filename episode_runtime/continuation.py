"""Exact interrupted-Run references; logical execution is not a process attempt.

This binding preserves the original program and input identity. It does not
authorize a launch or establish that a stopped worker's state can be restored.
"""

from dataclasses import dataclass

from agent.episode_contracts import OpaqueId, Sha256Digest


@dataclass(frozen=True)
class InterruptedRunRef:
    run_id: OpaqueId
    registration_hash: Sha256Digest
    terminal_event_id: OpaqueId
    terminal_event_hash: Sha256Digest

    def __post_init__(self):
        for key in ("run_id", "terminal_event_id"):
            if not isinstance(getattr(self, key), OpaqueId):
                raise TypeError(f"{key} must be an OpaqueId")
        for key in ("registration_hash", "terminal_event_hash"):
            if not isinstance(getattr(self, key), Sha256Digest):
                raise TypeError(f"{key} must be a Sha256Digest")

    def as_record(self):
        return {key: getattr(self, key).value for key in self.__dataclass_fields__}

    @classmethod
    def from_record(cls, value):
        from .contracts import _record

        record = _record(value, "interrupted Run reference", set(cls.__dataclass_fields__))
        return cls(
            OpaqueId(record["run_id"]), Sha256Digest(record["registration_hash"]),
            OpaqueId(record["terminal_event_id"]), Sha256Digest(record["terminal_event_hash"]),
        )

    @classmethod
    def from_run(cls, runs, run_id):
        """Bind the final committed boundary, never an earlier convenient prefix."""
        from .contracts import RunTerminalStatus

        run_id = OpaqueId(run_id) if isinstance(run_id, str) else run_id
        registration = runs.read_registration(run_id)
        evidence = runs.read_evidence(run_id)
        if evidence.terminal_status not in {
            RunTerminalStatus.INTERRUPTED,
            RunTerminalStatus.CANCELLED,
            RunTerminalStatus.RESOURCE_LIMITED,
        }:
            raise ValueError("only an interrupted, cancelled or resource-limited Run can be continued")
        events = runs.read_audit_log(run_id)
        terminal = events[-1]
        return cls(run_id, registration.registration_hash, terminal.event_id, terminal.event_hash)


def validate_resume_registration(runs, registration):
    """Store-side lineage validation; no evidence, credit or authority is copied."""
    reference = registration.resume_from
    if reference is None:
        return
    if reference.run_id == registration.run_id:
        raise ValueError("a Run cannot continue itself")
    actual = InterruptedRunRef.from_run(runs, reference.run_id)
    if actual != reference:
        raise ValueError("continuation reference differs from the final interrupted Run evidence")
    previous = runs.read_registration(reference.run_id)
    if (
        registration.logical_run_id != previous.logical_run_id
        or registration.logical_registration_hash != previous.logical_registration_hash
    ):
        raise ValueError("continuation cannot change code, inputs, authority, runtime or scope; start a new experiment")


def execution_lineage(runs, registration):
    """Oldest-first physical attempts of this exact logical execution.

    References are checked against terminal evidence, not a query by similar
    workflow or Episode ID. Original event ownership remains physical.
    """
    lineage, seen = [], set()
    current = registration
    while True:
        if current.run_id in seen:
            raise ValueError("continuation lineage contains a cycle")
        seen.add(current.run_id)
        lineage.append(current)
        if current.resume_from is None:
            return tuple(reversed(lineage))
        validate_resume_registration(runs, current)
        current = runs.read_registration(current.resume_from.run_id)
