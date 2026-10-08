"""Human-directed Target Workflow revisions through the existing Duet authority.

The editing conversation owns a working copy. A submitted snapshot is paired
with its exact human notes and approval; the next Refiner campaign starts from
those bytes, including unfinished plans and source.
"""

from pathlib import Path
import uuid

from agent.duet_contracts import canonical_json, content_id, digest_record
from agent.episode_contracts import OpaqueId
from episode_runtime.records.experiments import put_data, read_record, read_reference
from iterative_episode_refiner.campaign_store import CampaignView
from iterative_episode_refiner.evidence import EvidenceReader
from iterative_episode_refiner.human_workspace import HumanWorkflowWorkspace, WorkflowEditSnapshot, snapshot_from_candidate
from iterative_episode_refiner.materialization_edits import candidate_plan
from iterative_episode_refiner.records import Ref


def _rows(host, kind, **fields):
    clauses = " AND ".join("json_extract(record_json, ?) = ?" for _ in fields)
    params = [host.identity.duet_id.value, f"experiment.{kind}.v1"]
    for key, value in fields.items():
        params.extend((f"$.{key}", value))
    with host.store.transaction() as connection:
        rows = connection.execute(
            "SELECT artifact_id, content_hash FROM artifacts WHERE duet_id = ? AND kind = ?"
            + (" AND " + clauses if clauses else "") + " ORDER BY rowid",
            params,
        ).fetchall()
    return [read_reference(host.store, dict(row), host.identity.duet_id.value) for row in rows]


def record_edit_event(host, edit_id, event, **value):
    return put_data(host.store, host.identity.duet_id.value, "workflow_edit_event", {
        "edit_id": edit_id, "event": event, "nonce": uuid.uuid4().hex, **value,
    })


def edit_events(host, edit_id):
    return _rows(host, "workflow_edit_event", edit_id=edit_id)


def require_no_editor(host):
    """Keep a live coding workspace's writer separate from autonomous work."""
    from openchia_cli.active_sessions import _pid_liveness

    owners = _rows(host, "workflow_edit_ownership")
    if not owners or owners[-1]["record"]["released"]:
        return
    owner = owners[-1]["record"]
    if _pid_liveness(**owner["process"]) is not False:
        raise ValueError("The Target Workflow coding conversation owns editing; finish its handoff or close it before starting autonomous work")
    processes = [row["record"] for row in edit_events(host, owner["edit_id"])
                 if row["record"]["event"] in {"backend_started", "backend_closed"}]
    if processes and processes[-1]["event"] == "backend_started":
        if _pid_liveness(**processes[-1]["process"]) is not False:
            raise ValueError("The previous coding process is still live or unverifiable; its workspace cannot be reassigned")


def claim_edit(host, edit_id):
    from agent.openchia_build_recovery import owner_record

    with host.store.transaction():
        require_no_editor(host)
        return put_data(host.store, host.identity.duet_id.value, "workflow_edit_ownership", {
            "edit_id": edit_id, "process": owner_record(), "released": False,
            "claim_id": uuid.uuid4().hex,
        })


def release_edit(host, claim):
    with host.store.transaction():
        owner = _rows(host, "workflow_edit_ownership")[-1]
        if {key: owner[key] for key in ("artifact_id", "content_hash")} != claim:
            raise ValueError("Coding ownership changed before release")
        put_data(host.store, host.identity.duet_id.value, "workflow_edit_ownership", {
            **owner["record"], "released": True,
        })


def _quiet_target(host):
    """Transfer write ownership by joining the host's existing cancellation path."""
    host.cancel_run()
    host.cancel_build()
    with host._build_lock:
        build_worker = host._build_thread
    with host._run_lock:
        run_worker = host._run_thread
    for worker in (build_worker, run_worker):
        if worker is not None:
            worker.join()
    from agent.openchia_build_recovery import requested_jobs, require_owner_stopped

    jobs = requested_jobs(host)
    if jobs:
        require_owner_stopped(host, jobs[-1])
    for status in (host.build_status(), host.run_status()):
        if status.get("state") in {"starting", "building", "running", "continuing", "refining", "implementing", "validating", "cancel_requested", "ownership_unknown"}:
            raise ValueError("The owning OpenChia process must finish pausing this Target Workflow before editing can take ownership")


def prepare_edit(host, *, edit_id=None):
    """Snapshot the latest committed candidate after its active writer has stopped."""
    _quiet_target(host)
    with host._architecture_lock, host._build_lock:
        construction = _construction_edit_base(host)
        baseline = host.workspace.current_baseline()
        if baseline is None:
            raise ValueError("Coding a Target Workflow requires a materialized baseline, including a partial build")
        inputs = host.build_store.inspection_inputs_for_receipt(baseline.build_receipt_id)
        handoff = host.build_store.publish_materialization_handoff(baseline.build_receipt_id)
        plan = inputs.plan
        hashes = handoff["candidate"]["files"]
        predecessor = None
        job = read_record(host.store, "build_job", build_request_id=baseline.build_request_id.value)
        if job is not None:
            contract_ref = Ref.from_record(job["record"]["campaign_ref"])
            row = read_reference(host.store, contract_ref.as_record(), host.identity.duet_id.value)
            campaign_id = OpaqueId(row["record"]["campaign_id"])
            with host.store.transaction() as connection:
                view = CampaignView(connection, campaign_id)
                candidate, contract = view.candidate, view.contract
                if contract.ref != contract_ref or contract.body["target_approval_ref"]["artifact_id"] != baseline.authority_head_approval_id.value:
                    raise ValueError("Latest candidate belongs to another target authority")
                predecessor = {"campaign_ref": contract.ref.as_record(), "candidate_ref": candidate.ref.as_record(),
                               "campaign_commit_id": view.head["latest_commit_id"]}
            evidence = EvidenceReader(host.store, host.build_store, host.run_store)
            plan = candidate_plan(evidence, contract, candidate, inputs)
            hashes = candidate.body["files"]
        files = {path: host.build_store.read_blob(digest).decode("utf-8") for path, digest in hashes.items()}
        snapshot = snapshot_from_candidate(inputs, plan, files=files, handoff=handoff)
        job_request_id = baseline.build_request_id.value
        if construction is not None:
            snapshot, predecessor, job_request_id, handoff = construction
        edit_id = edit_id or content_id("workflow_edit", {"duet": host.identity.duet_id.value, "nonce": uuid.uuid4().hex}).value
        root = host.root / "workflow_edits" / edit_id
        context = {
            "edit_id": edit_id,
            "baseline": baseline.as_record(),
            "predecessor": predecessor,
            "model_slots": host.launch_design_context(),
            "source_files": "episodes/<local_id>.py; host declarations are attached at handoff",
            "architecture_file": "architecture.json",
            "materialization_file": "materialization.json",
            "design_intent_file": "change_intent.md",
            "initial_findings": handoff["diagnostics"],
            "refinement_history": "The predecessor identifies the retained campaign; earlier observations describe their original candidate, not this edited draft.",
        }
        workspace = HumanWorkflowWorkspace(root / "workspace", snapshot, context)
        workspace.stage()
        record = {"edit_id": edit_id, "baseline": baseline.as_record(), "predecessor": predecessor,
                  "build_job_request_id": job_request_id,
                  "workspace": str(workspace.root), "snapshot": snapshot.as_record(), "context": context}
        reference = put_data(host.store, host.identity.duet_id.value, "workflow_edit_session", record)
        return reference, record, workspace


def _construction_edit_base(host):
    """Checkpoint actual work for human review after the writer has stopped.

    This is source inspection at the editing boundary, not initial generation.
    The receipt may be blocked. Preserve the candidate's raw bytes separately
    so failed admission cannot discard the work being opened for editing.
    """
    import asyncio

    from agent.episode_launch import ResolvedLaunch
    from iterative_episode_refiner.campaign_store import CampaignStore
    from iterative_episode_refiner.candidate_source import admit_candidate

    request_id = host.build_status().get("build_request_id")
    if request_id is None:
        return None
    start = read_record(host.store, "construction_start", build_request_id=request_id)
    if start is None:
        return None
    inputs = host.build_store.inspection_inputs(**start["record"]["inputs"])
    handoff = start["record"]["handoff"]
    job = read_record(host.store, "build_job", build_request_id=request_id)
    evidence = EvidenceReader(host.store, host.build_store, host.run_store)
    predecessor, plan, hashes = None, inputs.plan, handoff["candidate"]["files"]
    if job is not None:
        row = read_reference(host.store, job["record"]["campaign_ref"], host.identity.duet_id.value)
        with host.store.transaction() as connection:
            view = CampaignView(connection, OpaqueId(row["record"]["campaign_id"]))
            candidate, contract = view.candidate, view.contract
            if contract.body["target_approval_ref"]["artifact_id"] != inputs.build_request.authority_approval.approval_id.value:
                raise ValueError("Construction candidate belongs to another target authority")
            predecessor = {"campaign_ref": contract.ref.as_record(), "candidate_ref": candidate.ref.as_record(),
                           "campaign_commit_id": view.head["latest_commit_id"]}
        plan = candidate_plan(evidence, contract, candidate, inputs)
        hashes = candidate.body["files"]
    snapshot = snapshot_from_candidate(inputs, plan, handoff=handoff, files={
        path: host.build_store.read_blob(digest).decode("utf-8") for path, digest in hashes.items()
    })
    launches = [event["record"] for event in host.store.events(host.identity.duet_id.value)
                if event["event_type"] == "model_launch_resolved"
                and event["record"]["kind"] == "build" and event["record"]["subject_id"] == request_id]
    if len(launches) != 1:
        raise ValueError("Construction checkpoint requires its recorded launch configuration")
    # Static inspection needs configuration identity, never credentials or a transport.
    launch = ResolvedLaunch(canonical_json(launches[0]["configuration"]), {})
    if launch.configuration_hash != launches[0]["configuration_hash"]:
        raise ValueError("Recorded construction launch identity changed")
    builder = host._builder_for(inputs.build_request, launch)
    if job is not None:
        receipt = admit_candidate(CampaignStore(host.store, evidence), contract, candidate, builder)
    else:
        receipts = host.build_store.receipts_for_build_request(inputs.build_request.build_request_id)
        if len(receipts) > 1:
            raise ValueError("Construction input has ambiguous admission receipts")
        receipt = receipts[0] if receipts else None
        if receipt is None:
            receipt = asyncio.run(builder.admit_sources(
                build_request=inputs.build_request, build_attempt=inputs.build_attempt,
                plan=inputs.plan, emitted_modules=inputs.emitted_modules,
            ))
    host._persist_materialized_specification(host.build_store.read_build_request(receipt.build_request_id), receipt)
    return snapshot, predecessor, request_id, host.build_store.read_materialization_handoff(receipt.receipt_id)


def load_edit(host, edit_id=None):
    rows = _rows(host, "workflow_edit_session", **({"edit_id": edit_id} if edit_id else {}))
    if not rows:
        raise ValueError("No saved Target Workflow coding conversation exists for this Duet")
    row = rows[-1]
    value = row["record"]
    root = host.root / "workflow_edits" / value["edit_id"] / "workspace"
    if Path(value["workspace"]) != root or not root.is_dir() or root.is_symlink():
        raise ValueError("Saved workflow editing workspace is missing or changed")
    reference = {key: row[key] for key in ("artifact_id", "content_hash")}
    workspace = HumanWorkflowWorkspace(root, WorkflowEditSnapshot.from_record(value["snapshot"]), value["context"])
    return reference, value, workspace


def require_current_edit_base(host, record):
    baseline = host.workspace.current_baseline()
    if baseline is None or baseline.as_record() != record["baseline"]:
        raise ValueError("The Target Workflow changed since this coding conversation began; open a new draft against the newer baseline")
    job = read_record(host.store, "build_job", build_request_id=record["build_job_request_id"])
    if job is not None:
        predecessor = record["predecessor"]
        if predecessor is None or job["record"]["campaign_ref"] != predecessor["campaign_ref"]:
            raise ValueError("New refinement work exists; open a new coding draft so it is retained")
        contract = read_reference(host.store, predecessor["campaign_ref"], host.identity.duet_id.value)
        with host.store.transaction() as connection:
            view = CampaignView(connection, OpaqueId(contract["record"]["campaign_id"]))
            if view.candidate.ref.as_record() != predecessor["candidate_ref"]:
                raise ValueError("The Refiner committed a newer candidate; open a new draft before combining it with saved edits")
    return baseline


def submit_edit(host, record, workspace):
    """Freeze the actual draft for existing human review; never self-approve."""
    # Proposal, human notes and frozen source are one authority transaction.
    # A failed source publication must leave no approvable source-less proposal.
    with host._architecture_lock, host._build_lock, host.store.transaction():
        baseline = require_current_edit_base(host, record)
        if host.has_active_work():
            raise ValueError("The Target Workflow must be paused before submitting its edited revision")
        snapshot = workspace.capture()
        if not snapshot.diff(workspace.baseline):
            raise ValueError("This coding conversation has no draft changes to submit")
        if not snapshot.intent.strip():
            raise ValueError("Record the intended behavior and design correspondence in change_intent.md before handoff")
        messages = [row["record"]["text"] for row in edit_events(host, record["edit_id"])
                    if row["record"]["event"] == "human_message"]
        if not messages:
            raise ValueError("A human instruction is required for this revision")
        notes = tuple(note for index, text in enumerate(messages)
                      for note in host.record_global_instruction(text, f'{record["edit_id"]}_{index}'))
        implementation_notes = [note for note in notes if note["target"]["layer"] == "materialization_implementation"]
        if not implementation_notes:
            raise ValueError("The human instructions could not be attached to the materialized baseline")
        # The assistant's synthesis is a proposal grounded in actual human text.
        # The normal /approve command remains the only authority transition.
        proposal = host.request_episode_refinement(
            baseline_id=baseline.baseline_id.value,
            candidate_workflow_architecture=snapshot.architecture,
            human_note_ids=tuple(note["note_id"] for note in notes),
            implementation_directives=({
                "human_note_id": implementation_notes[-1]["note_id"],
                "target_id": implementation_notes[-1]["target"]["target_id"],
                "instruction": snapshot.intent,
            },),
        )
        if not proposal.get("accepted"):
            raise ValueError(f"Edited design was not admitted: {proposal}")
        reference = put_data(host.store, host.identity.duet_id.value, "workflow_edit_submission", {
            "edit_id": record["edit_id"], "proposal_id": proposal["proposal_id"],
            "baseline": record["baseline"], "predecessor": record["predecessor"],
            "snapshot": snapshot.as_record(), "human_messages": messages,
            "snapshot_hash": digest_record(snapshot.as_record()).value,
        })
        record_edit_event(host, record["edit_id"], "submitted", submission_ref=reference, **proposal)
        return proposal


def approved_edit(host, request):
    """Resolve the bytes bound to this exact approved revision, independent of disk."""
    if request.refinement_proposal is None:
        return None
    rows = _rows(host, "workflow_edit_submission", proposal_id=request.refinement_proposal.proposal_id.value)
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("Approved revision has conflicting coding submissions")
    row, value = rows[0], rows[0]["record"]
    from agent.episode_blueprints import workflow_spec_from_blueprint

    if (digest_record(value["snapshot"]).value != value["snapshot_hash"]
            or workflow_spec_from_blueprint(value["snapshot"]["architecture"]) != request.frozen_workflow.workflow
            or canonical_json(value["baseline"]) != canonical_json(request.refinement_baseline.as_record())
            or value["snapshot"]["intent"] not in {d.instruction for d in request.refinement_proposal.implementation_directives}):
        raise ValueError("Coding submission differs from the human-approved revision")
    return {"reference": {key: row[key] for key in ("artifact_id", "content_hash")}, **value}
