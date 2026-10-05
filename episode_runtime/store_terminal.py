"""Operation-scoped reuse of independently verified immutable terminal history.

Only explicitly named Runs can be retained. Current authority, campaign state
and physical active prefixes never enter this scope. The scope follows normal
ContextVar propagation into host threads and is discarded when its owner exits.
"""

from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock

from agent.episode_contracts import OpaqueId

from .audit_contracts import RunEvidence
from .contracts import InspectedExecutorAttestation, RunEvent, RunRegistration


@dataclass(frozen=True)
class VerifiedTerminalSnapshot:
    registration: RunRegistration
    attestation: InspectedExecutorAttestation
    evidence: RunEvidence
    events: tuple[RunEvent, ...]


@dataclass
class _Scope:
    store: object
    run_ids: frozenset[OpaqueId]
    snapshots: dict[OpaqueId, VerifiedTerminalSnapshot] = field(default_factory=dict)
    lock: AbstractContextManager = field(default_factory=RLock)
    active: bool = True


_SCOPES: ContextVar[tuple[_Scope, ...]] = ContextVar("terminal_snapshot_scopes", default=())


@contextmanager
def terminal_snapshot_scope(store, run_ids):
    """Pin named terminal histories for one operation, never across operations."""
    selected = frozenset(run_ids)
    if any(not isinstance(run_id, OpaqueId) for run_id in selected):
        raise TypeError("terminal snapshot scope requires exact Run IDs")
    scope = _Scope(store, selected)
    token = _SCOPES.set((*_SCOPES.get(), scope))
    try:
        yield
    finally:
        # Cancellation can leave an awaited to_thread verification finishing.
        # Closing its owner must not block the event loop on that thread's lock.
        scope.active = False
        scope.snapshots.clear()
        _SCOPES.reset(token)


def _anchors(store, run_id):
    from .store import RunStoreCorruption

    registration = store.read_registration(run_id)
    attestation = store.read_claim(run_id)
    record = store._read_record(store._evidence_path(run_id), "terminal Run evidence")
    try:
        evidence = RunEvidence.from_record(record)
    except (TypeError, ValueError) as exc:
        raise RunStoreCorruption("terminal Run evidence contract is invalid") from exc
    return registration, attestation, evidence


def _verify(store, run_id):
    from .store import RunStoreCorruption

    with store._claim_lock(run_id):
        registration, attestation, evidence = _anchors(store, run_id)
        events = store._load_event_chain_locked(registration, attestation)
        audit_log, chunks = store._read_audit_log_locked(evidence)
        try:
            evidence.validate_against(registration, attestation, audit_log, chunks)
        except (TypeError, ValueError) as exc:
            raise RunStoreCorruption(
                "terminal Run evidence does not match its event chain"
            ) from exc
        if audit_log.validate_chunks(chunks) != events:
            raise RunStoreCorruption(
                "terminal audit chunks differ from append-only event records"
            )
        return VerifiedTerminalSnapshot(registration, attestation, evidence, events)


def _same_identity(snapshot, anchors):
    from .store import RunStoreCorruption

    if (snapshot.registration, snapshot.attestation, snapshot.evidence) != anchors:
        raise RunStoreCorruption("terminal Run identity changed during its snapshot scope")


def read_terminal_snapshot(store, run_id, *, verify=False):
    """Reuse only verified history; explicit verification always rereads disk.

    Reuse rechecks the small immutable identity records, not every event/chunk.
    Callers requesting a fresh audit must use verify=True, including inside a
    scope. A failed check discards the retained snapshot before propagating.
    """
    # Prefer the outer owner so nested operations reuse its exact snapshot.
    scope = next((
        item for item in _SCOPES.get()
        if item.active and item.store is store and run_id in item.run_ids
    ), None)
    if scope is None:
        return _verify(store, run_id)
    with scope.lock:
        if not scope.active:
            return _verify(store, run_id)
        previous = scope.snapshots.get(run_id)
        try:
            if previous is not None and not verify:
                with store._claim_lock(run_id):
                    _same_identity(previous, _anchors(store, run_id))
                return previous
            snapshot = _verify(store, run_id)
            if previous is not None:
                _same_identity(previous, (
                    snapshot.registration, snapshot.attestation, snapshot.evidence,
                ))
            if scope.active:
                scope.snapshots[run_id] = snapshot
            return snapshot
        except Exception:
            scope.snapshots.pop(run_id, None)
            raise
