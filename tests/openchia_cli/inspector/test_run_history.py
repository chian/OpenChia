"""Actual RunStore journals and continuation identities, without worker execution."""

from dataclasses import replace
import json

import pytest

from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.records.experiments import put_record
from tests.episode_runtime.conftest import claim_store
from openchia_cli.inspector.refiner import Refiner, Selection
from openchia_cli.inspector.refiner_controller import RefinerController
from openchia_cli.inspector.archive import InspectionError
from openchia_cli.refiner_command import main


@pytest.mark.asyncio
async def test_run_cursor_never_substitutes_newer_campaign_or_terminal_state(observer_home, campaign):
    session = campaign.session
    runs, registration = session.store.evidence.runs, session.registration
    claim_store(runs.root, registration, store=runs)
    put_record(campaign.duets, 'refinement_job', duet_id=session.duet_id,
               campaign_id=campaign.campaign_id.value, record={
                   'experiment_id': 'observer-test', 'campaign_ref': session.contract.ref.as_record(),
                   'starting_state': session.continuation_state()['campaign_head'],
                   'registration': registration.as_record(),
               })
    runs.append_event(run_id=registration.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
                      kind=RunEventKind.RUN_STARTED, episode_id=None, payload={})
    anchor = session.continuation_state()
    runs.append_event(run_id=registration.run_id, origin=RunEventOrigin.HOST, sender_sequence=1,
                      kind=RunEventKind.REFINEMENT_RESPONDED, episode_id=None, payload={'session_state': anchor})
    campaign.implementer()
    source = Refiner(observer_home)
    controller = RefinerController(source, Selection(run=registration.run_id.value))
    controller.capture()
    assert not controller.live
    assert controller.selection.event == 1
    selection = Selection(run=registration.run_id.value, event=1)
    historic = source.capture(selection)
    assert len(historic.snapshot.nodes) < len(source.capture().snapshot.nodes)
    assert historic.snapshot.position['step'] == anchor['campaign_head']['sequence']
    runs.finalize_run(run_id=registration.run_id, origin=RunEventOrigin.HOST, sender_sequence=2,
                      terminal_status=RunTerminalStatus.INTERRUPTED, typed_status={'reason': 'observation fixture'})
    detail = source.capture(selection).reference('run', registration.run_id.value)
    assert detail.sections['summary']['recorded_status'] == 'no recorded terminal event'
    assert detail.sections['events'][-1]['sequence'] == 1
    assert controller.capture().snapshot.position['run_event'] == 1
    resumed = replace(registration, resume_from=InterruptedRunRef.from_run(runs, registration.run_id))
    claim_store(runs.root, resumed, store=runs)
    runs.append_event(run_id=resumed.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
                      kind=RunEventKind.REFINEMENT_RESPONDED, episode_id=None,
                      payload={'session_state': session.continuation_state()})
    assert resumed.run_id.value in {link.identity for link in source.capture().run_links()}
    assert resumed.run_id.value not in {link.identity for link in historic.run_links()}
    with pytest.raises(InspectionError, match='historical position'):
        historic.reference('run', resumed.run_id.value)
    continued = source.capture(Selection(run=resumed.run_id.value, event=0))
    assert continued.snapshot.identity == historic.snapshot.identity
    assert continued.snapshot.position['run_id'] != historic.snapshot.position['run_id']
    assert continued.snapshot.position['step'] > historic.snapshot.position['step']
    early = source.capture(Selection(run=registration.run_id.value, event=0))
    assert early.snapshot.gaps and not early.snapshot.nodes
    assert early.reference('run', registration.run_id.value).sections['events'][0]['kind'] == 'run_started'
    output = []
    assert main(['history', '--home', str(observer_home), '--run', registration.run_id.value,
                 '--event', '1', '--json'], emit=output.append) == 0
    assert [row['event'] for row in json.loads(output[0])] == [0, 1]


@pytest.mark.asyncio
async def test_reference_from_campaign_history_reports_missing_run_boundary(observer_home, campaign):
    session = campaign.session
    runs, registration = session.store.evidence.runs, session.registration
    claim_store(runs.root, registration, store=runs)
    put_record(campaign.duets, 'refinement_job', duet_id=session.duet_id,
               campaign_id=campaign.campaign_id.value, record={
                   'experiment_id': 'observer-test', 'campaign_ref': session.contract.ref.as_record(),
                   'starting_state': session.continuation_state()['campaign_head'],
                   'registration': registration.as_record(),
               })
    # The job was recorded between commits, so a time cursor includes it.
    from datetime import datetime, timezone
    # A BOM added by Windows tooling does not change the registered JSON record.
    registration_path = runs.root / 'registrations' / f'{registration.run_id.value}.json'
    registration_path.write_bytes(b'\xef\xbb\xbf' + registration_path.read_bytes())
    source = Refiner(observer_home)
    view = source.capture(Selection(at_time=datetime.now(timezone.utc).isoformat()))
    detail = view.reference('run', registration.run_id.value)
    assert detail.gaps
    assert 'events' not in detail.sections


@pytest.mark.asyncio
async def test_bad_run_publication_is_a_gap_and_selected_bad_event_is_an_observation_error(observer_home, campaign):
    from openchia_cli.inspector.archive import canonical_hash

    session = campaign.session
    runs, registration = session.store.evidence.runs, session.registration
    claim_store(runs.root, registration, store=runs)
    put_record(campaign.duets, 'refinement_job', duet_id=session.duet_id,
               campaign_id=campaign.campaign_id.value, record={
                   'campaign_ref': session.contract.ref.as_record(), 'registration': registration.as_record(),
               })
    directory = runs.root / 'registrations'
    (directory / 'partial.json').write_text('{')
    (directory / 'array.json').write_text('[]')
    (directory / 'symlink.json').symlink_to(directory / f'{registration.run_id.value}.json')
    (directory / 'bad_predecessor.json').write_text(json.dumps({
        'run_id': 'bad_predecessor', 'registration_hash': 'sha256:fixture', 'resume_from': [],
    }))
    (directory / '.publication.json').write_text('{')

    source = Refiner(observer_home)
    controller = RefinerController(source)
    view = controller.capture()
    assert registration.run_id.value in {link.identity for link in view.run_links()}
    detail = view.detail(view.snapshot.nodes[0].identity)
    assert len(detail.gaps) == 4
    assert all(any(name in gap for gap in detail.gaps)
               for name in ('partial.json', 'array.json', 'symlink.json', 'bad_predecessor.json'))
    with pytest.raises(InspectionError, match='partial.json'):
        view.reference('run', 'partial')
    for name in ('partial', 'array', 'symlink', 'bad_predecessor'):
        (directory / f'{name}.json').unlink()
    assert not controller.capture().snapshot.gaps
    assert detail.gaps  # Already captured observations retain their original gaps.

    empty = source.capture(Selection(run=registration.run_id.value))
    assert empty.reference('run', registration.run_id.value).sections['summary']['last_event'] is None
    runs.append_event(run_id=registration.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
                      kind=RunEventKind.RUN_STARTED, episode_id=None, payload={})
    event_path = runs.root / 'events' / registration.run_id.value / f'{0:020d}.json'
    record = json.loads(event_path.read_text())
    del record['payload']
    record['event_hash'] = canonical_hash({key: value for key, value in record.items() if key != 'event_hash'})
    event_path.write_text(json.dumps(record))
    output = []
    assert main(['history', '--home', str(observer_home), '--run', registration.run_id.value, '--json'],
                emit=output.append) == 2
    error = json.loads(output[-1])
    assert error['kind'] == 'observation_unavailable'
    assert 'payload' in error['error'] and registration.run_id.value in error['error']
