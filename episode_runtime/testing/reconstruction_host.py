"""The existing executor's switch from verified history to new work.

The worker runs its ordinary linked Episode loop. Before this switch every
request is answered from the shared journal, never from a broker or session.
Only the host may admit the boundary; exhausting a recording is insufficient.
"""

import asyncio

from ..continuation import validate_resume_registration
from ..contracts import RunEventKind, RunEventOrigin
from ..linker import prepare_source_package
from .reconstruction import ReconstructionCursor, ReconstructionError
from .reconstruction_source import admit_reconstruction_source


class HostReconstruction:
    def __init__(self, runs, registration, source_receipt, *, refinement_session=None, experiment_session=None):
        validate_resume_registration(runs, registration)
        if registration.resume_from is None:
            raise ValueError("reconstruction requires an exact interrupted execution")
        self.runs, self.registration = runs, registration
        self.cursor = ReconstructionCursor(
            runs, registration.resume_from.run_id,
            artifacts=None if refinement_session is None else refinement_session.store.duet_store,
        )
        self.source_receipt = source_receipt
        self.refinement_session = refinement_session
        self.experiment_session = experiment_session
        self.activated = False
        families = {row["family"] for row in source_receipt["modules"]}
        if "refinement" in families and refinement_session is None:
            raise ReconstructionError("refinement continuation requires restored host call state")
        if "testing" in families and experiment_session is None:
            raise ReconstructionError("testing continuation requires its admitted experiment session")
        self._validate_sessions()

    def _validate_sessions(self):
        for session in (self.refinement_session, self.experiment_session):
            if session is not None:
                session.validate_registration(self.registration)
        if self.refinement_session is not None:
            from iterative_episode_refiner.runtime_state import validate_restored_state, validate_unstarted_session

            saved = self.cursor.host_state
            if saved is None or saved["state"] is None:
                if self.cursor.prefix_verified:
                    validate_unstarted_session(self.refinement_session)
                    return
                raise ReconstructionError("no committed refinement state at the interrupted boundary")
            validate_restored_state(self.refinement_session, saved["state"])

    async def consume(self, frame, channel, *, authorize):
        """Return true for a historical frame; false delegates to normal brokers.

        authorize is the host service's current approval/configuration check,
        combined by the executor with its read-only stopped-process inspection.
        It is never a worker-supplied flag or model judgment.
        """
        if self.activated:
            return False
        empty = self.cursor.prefix_verified
        reply = None if empty else self.cursor.accept(frame)
        if self.cursor.prefix_verified:
            authority = await authorize()
            await asyncio.to_thread(self._validate_sessions)
            await asyncio.to_thread(
                self.runs.append_event,
                run_id=self.registration.run_id,
                origin=RunEventOrigin.HOST_RECONSTRUCTION,
                sender_sequence=0,
                kind=RunEventKind.RUN_RECONSTRUCTED,
                episode_id=None,
                payload={
                    "resume_from": self.registration.resume_from.as_record(),
                    "source_admission": self.source_receipt,
                    "reconstruction": self.cursor.report(),
                    "activation_admission": authority,
                },
            )
            self.activated = True
        if reply is not None:
            await channel.send(reply.frame_type, reply.body)
        # The final request was matched, not answered. Only after the host
        # activation receipt commits may the ordinary broker send it again.
        return not empty and not self.cursor.retry_pending_request


def prepare_reconstruction(runs, registration, source_package, runtime_manifest, *, refinement_session=None, experiment_session=None):
    """Fail before publishing a new Run if its code/history cannot be continued."""
    prepared = prepare_source_package(registration, source_package)
    receipt = admit_reconstruction_source(
        prepared, source_package_path=source_package, runtime_manifest=runtime_manifest,
    )
    return HostReconstruction(
        runs, registration, receipt,
        refinement_session=refinement_session, experiment_session=experiment_session,
    )
