"""Observation invariants across real admission, commits, and concurrent writes."""

import json
import math
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from openchia_cli.inspector.archive import InspectionError
from openchia_cli.inspector.refiner import Refiner, Selection
from openchia_cli.inspector.navigation import Navigation
from openchia_cli.refiner_command import main


@pytest.mark.asyncio
async def test_nested_history_keeps_versions_and_evidence_distinct(observer_home, campaign):
    source = Refiner(observer_home)
    initial = source.capture()
    root = initial.snapshot.nodes[0]
    campaign.implementer()
    # Persist sub-microsecond time precision, as time.time() does in production.
    # A timestamp copied from the viewer must still select this publication.
    with sqlite3.connect(campaign.duets.path) as db:
        identity, recorded = db.execute(
            'SELECT a.artifact_id,a.created_at FROM artifacts a '
            'JOIN refinement_campaign_heads h ON h.latest_commit_id=a.artifact_id '
            'WHERE h.campaign_id=?', (campaign.campaign_id.value,)).fetchone()
        rounded = datetime.fromtimestamp(recorded, timezone.utc).timestamp()
        db.execute('UPDATE artifacts SET created_at=? WHERE artifact_id=?',
                   (math.nextafter(rounded, math.inf), identity))
    entered = source.capture()
    implementer = next(n for n in entered.snapshot.nodes if n.label == 'Implementer')
    assert entered.snapshot.nodes[0].status == 'waiting'
    assert implementer.parent != root.identity
    assert next(n for n in entered.snapshot.nodes if n.identity == implementer.parent).parent == root.identity
    revision = campaign.change(b'# observation test\n' + campaign.initial_source)
    campaign.store.commit_attempt(revision)
    campaign.perform('close_unit', {'candidate_before_ref': campaign.initial.ref.as_record(), 'continuation_ref': None})
    current = source.capture()
    assert current.candidate_id != initial.candidate_id
    assert current.detail(implementer.identity).sections['iterations'][0]['record']['body']['realized_yield'] == 0
    historic = source.capture(Selection(at=entered.snapshot.position['step']))
    assert historic.candidate_id == entered.candidate_id
    assert historic.detail(implementer.identity).sections['iterations'] == []
    with pytest.raises(InspectionError, match='unavailable'):
        historic.reference('artifact', current.candidate_id)
    by_time = source.capture(Selection(at_time=entered.snapshot.position['time']))
    assert by_time.snapshot.position['selected_time'] == entered.snapshot.position['time']
    assert by_time.candidate_id == entered.candidate_id
    assert by_time.snapshot.position['step'] == entered.snapshot.position['step']
    candidate = current.reference('artifact', current.candidate_id)
    assert candidate.domain == 'candidate'
    assert candidate.sections['file_changes'][0]['before'] != candidate.sections['file_changes'][0]['after']
    workflow = current.reference('artifact', current.snapshot.links[0].identity)
    assert workflow.domain == 'target_workflow'
    output = []
    assert main(['show', '--home', str(observer_home), '--node', implementer.identity, '--json'], emit=output.append) == 0
    assert json.loads(output[0])['detail'] == current.detail(implementer.identity).as_dict()
    old = source.capture(Selection(at=initial.snapshot.position['step']))
    assert [n.identity for n in old.snapshot.nodes] == [root.identity]


@pytest.mark.asyncio
async def test_observer_does_not_write_or_block_publication(observer_home, campaign):
    source = Refiner(observer_home)
    campaign.implementer()
    frozen = source.capture()
    attempt = campaign.change(b'# concurrent publication\n' + campaign.initial_source)
    with source.archive.connection() as db:
        previous = db.execute('SELECT candidate_id FROM refinement_campaign_heads WHERE campaign_id=?',
                              (campaign.campaign_id.value,)).fetchone()[0]
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute('CREATE TABLE observer_must_not_write (value TEXT)')
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(campaign.store.commit_attempt, attempt).result(timeout=10)
        assert db.execute('SELECT candidate_id FROM refinement_campaign_heads WHERE campaign_id=?',
                          (campaign.campaign_id.value,)).fetchone()[0] == previous
    assert source.capture().candidate_id != frozen.candidate_id
    assert frozen.reference('artifact', previous).identity == previous
    with campaign.duets.transaction() as db:
        before = db.execute('SELECT count(*) FROM artifacts').fetchone()[0]
    source.capture().detail(campaign.current_invocation.value)
    with campaign.duets.transaction() as db:
        assert db.execute('SELECT count(*) FROM artifacts').fetchone()[0] == before


@pytest.mark.asyncio
async def test_navigation_holds_selection_and_coding_agent_reads_bound_profile(observer_home, campaign, tmp_path, monkeypatch):
    from agent.secret_scope import is_multiplex_active, set_multiplex_active
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from agent.duet_store import DuetStore

    source = Refiner(observer_home)
    campaign.implementer()
    view = source.capture()
    nav = Navigation()
    nav.update(view.snapshot)
    assert nav.selected == campaign.current_invocation.value
    nav.move(-1)
    held = nav.selected
    nav.focus_selected()
    nav.update(source.capture().snapshot)
    assert nav.selected == held and nav.focus == held
    second = tmp_path / 'other-profile'
    with DuetStore(second / 'openchia' / 'authority.sqlite3'):
        pass
    monkeypatch.setenv('HERMES_HOME', str(second))
    previous = is_multiplex_active()
    set_multiplex_active(True)
    try:
        for home, expected in ((observer_home, True), (second, False), (observer_home, True)):
            token = set_hermes_home_override(home)
            try:
                output = []
                assert main(['list', '--json'], emit=output.append) == 0
                assert bool(json.loads(output[0])) is expected
            finally:
                reset_hermes_home_override(token)
    finally:
        set_multiplex_active(previous)


@pytest.mark.asyncio
async def test_return_and_supersession_remain_separate_historical_states(observer_home, campaign):
    """Publish transition fixtures in the real journal format; no admission claim."""
    from iterative_episode_refiner.campaign_store import CampaignView
    from iterative_episode_refiner.state_machine import index

    assignment = campaign.designer()
    iid = campaign.current_invocation.value
    source = Refiner(observer_home)
    active = source.capture()
    replacement = campaign.record('assignment', {
        **assignment.body, 'supersedes_assignment_refs': [assignment.ref.as_record()],
    })
    replacement_iid = iid + '_replacement'

    def publish(status):
        attempt = campaign.attempt('return_child', {})
        with campaign.duets.transaction() as db:
            view = CampaignView(db, campaign.campaign_id)
            predecessor = view.read(view.head['latest_commit_id']).ref
            records = [attempt]
            deltas = [index('invocation', iid, assignment, status),
                      index('assignment', assignment.artifact_id.value, assignment,
                            'superseded' if status == 'superseded' else 'active')]
            if status == 'superseded':
                records.append(replacement)
                deltas.extend([index('invocation', replacement_iid, replacement, 'active'),
                               index('assignment', replacement.artifact_id.value, replacement)])
            commit = campaign.record('commit', {
                'previous_commit_ref': predecessor.as_record(), 'sequence': view.head['sequence'] + 1,
                'attempt_ref': attempt.ref.as_record(), 'deltas': deltas,
            }, predecessor_refs=(predecessor,))
            for record in (*records, commit):
                campaign.store._put(db, campaign.session.duet_id, record)
            campaign.store._apply(db, view, commit)
        return source.capture()

    returned = publish('returned')
    replaced = publish('superseded')
    for frozen, state in ((active, 'active'), (returned, 'returned'), (replaced, 'superseded')):
        historical = source.capture(Selection(at=frozen.snapshot.position['step']))
        assert next(n.status for n in historical.snapshot.nodes if n.identity == iid) == state
        assert 'accepted' not in historical.detail(iid).sections['summary']['recorded_status']
        assert all(row['step'] <= frozen.snapshot.position['step'] for row in historical.snapshot.timeline)
        assert (replacement_iid in {node.identity for node in historical.snapshot.nodes}) == (state == 'superseded')
    assert next(n.parent for n in replaced.snapshot.nodes if n.identity == replacement_iid) == next(
        n.parent for n in returned.snapshot.nodes if n.identity == iid)
    assert assignment.ref.as_record() in replaced.detail(replacement_iid).sections['assignment']['body']['supersedes_assignment_refs']
    with pytest.raises(InspectionError, match='unavailable'):
        source.capture(Selection(at=returned.snapshot.position['step'])).reference('artifact', replacement.artifact_id.value)
    # Existing experiment receipts retain the report envelope's inner identity
    # while assigning a separate outer receipt identity.
    from episode_runtime.records.experiments import put_record, record_id
    put_record(campaign.duets, 'refinement_result_attempt', duet_id=campaign.session.duet_id,
               experiment_id='viewer-history-fixture', run_id='fixture-run', record=assignment.as_record())
    receipt_id = record_id('refinement_result_attempt', experiment_id='viewer-history-fixture', run_id='fixture-run')
    receipt = source.capture().reference('artifact', receipt_id)
    assert receipt.identity == receipt_id
    assert receipt.sections['record']['artifact_id'] == assignment.artifact_id.value
    assert receipt.identity != receipt.sections['record']['artifact_id']
    campaign.duets.put_artifact(artifact_id='semantic_receipt_alias', duet_id=campaign.session.duet_id,
                               kind='experiment.refinement_result_attempt.v1', revision=1,
                               content_hash=assignment.content_hash.value, record=assignment.as_record())
    assert source.capture().reference('artifact', 'semantic_receipt_alias').sections['record'] == assignment.as_record()
    # An unattached commit artifact is a stored proposal, not operative history.
    latest = replaced.snapshot.position['step']
    with campaign.duets.transaction() as db:
        view = CampaignView(db, campaign.campaign_id)
        attempt = campaign.attempt('return_child', {})
        orphan = campaign.record('commit', {
            'previous_commit_ref': None, 'sequence': latest + 10,
            'attempt_ref': attempt.ref.as_record(), 'deltas': [],
        })
        campaign.store._put(db, campaign.session.duet_id, orphan)
    assert source.capture().snapshot.position['step'] == latest
    with sqlite3.connect(campaign.duets.path) as db:
        db.execute("UPDATE refinement_campaign_heads SET latest_commit_id='missing-history' WHERE campaign_id=?",
                   (campaign.campaign_id.value,))
    with pytest.raises(InspectionError, match='missing'):
        source.capture()
