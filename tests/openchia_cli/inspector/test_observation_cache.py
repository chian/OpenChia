"""Unchanged observations do no replay work; new publications remain visible."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from openchia_cli.inspector.archive import InspectionError
from openchia_cli.inspector import archive
from openchia_cli.inspector.refiner import Refiner, Selection
from openchia_cli.inspector.refiner_controller import RefinerController


@pytest.mark.asyncio
async def test_poll_and_growth_reuse_verification_without_leaking_future_records(observer_home, campaign, monkeypatch):
    campaign.implementer()
    source = Refiner(observer_home)
    controller = RefinerController(source)
    verified, projections = [], []
    hash_record, capture = archive.canonical_hash, source.capture

    def counted_hash(record):
        digest = hash_record(record)
        verified.append(digest)
        return digest

    def counted_capture(selection):
        projections.append(selection)
        return capture(selection)

    monkeypatch.setattr(archive, 'canonical_hash', counted_hash)
    monkeypatch.setattr(source, 'capture', counted_capture)
    first = controller.capture()
    iid = campaign.current_invocation.value
    first_detail = first.detail(iid)
    initial_verifications = tuple(verified)
    unchanged = controller.capture()
    assert unchanged.snapshot.nodes == first.snapshot.nodes
    assert unchanged.detail(iid).as_dict() == first_detail.as_dict()
    assert len(projections) == 1
    assert tuple(verified) == initial_verifications

    # A publication without a new commit must invalidate the live observation.
    attempt = campaign.attempt('return_child', {})
    with campaign.duets.transaction() as db:
        campaign.store._put(db, campaign.session.duet_id, attempt)
    newer = controller.capture()
    newer_detail = newer.detail(iid)
    assert newer.snapshot.position['step'] == first.snapshot.position['step']
    assert attempt.artifact_id.value in {row['artifact_id'] for row in newer_detail.sections['activity']}
    assert attempt.artifact_id.value not in {row['artifact_id'] for row in first.detail(iid).sections['activity']}
    assert set(verified[len(initial_verifications):]) == {hash_record(attempt.as_record()), attempt.content_hash.value}
    with pytest.raises(InspectionError, match='historical position'):
        first.reference('artifact', attempt.artifact_id.value)

    change = campaign.change(b'# cache publication fixture\n' + campaign.initial_source)
    campaign.store.commit_attempt(change)
    after_commit = controller.capture()
    assert after_commit.candidate_id != first.candidate_id
    assert not set(initial_verifications).intersection(verified[len(initial_verifications):])
    historical = source.capture(Selection(at=first.snapshot.position['step']))
    assert historical.candidate_id == first.candidate_id
    assert attempt.artifact_id.value not in {row['artifact_id'] for row in historical.detail(iid).sections['activity']}


@pytest.mark.asyncio
async def test_refresh_cannot_overwrite_cursor_changed_while_reading(observer_home, campaign, monkeypatch):
    campaign.implementer()
    source = Refiner(observer_home)
    controller = RefinerController(source)
    view = source.capture()
    capture = source.capture
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def blocked_capture(selection):
        result = capture(selection)
        loop.call_soon_threadsafe(started.set)
        if not release.wait(15):
            raise AssertionError('Reader was not released')
        return result

    monkeypatch.setattr(source, 'capture', blocked_capture)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(controller.capture)
        try:
            await asyncio.wait_for(started.wait(), 15)
            controller.step(view, -1)
            selected = controller.selection
        finally:
            release.set()
        pending.result(timeout=15)
    assert controller.selection == selected
    assert controller.capture().snapshot.position['step'] == view.snapshot.position['step'] - 1
